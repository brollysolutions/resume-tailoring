"""Apply resume tailoring suggestions to Resume objects."""
import logging
import re
from app.models.resume_schema import Resume

logger = logging.getLogger(__name__)

_LEADING_BULLET_RE = re.compile(r"^\s*[-•*—‒–·]\s*")
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def _set_by_path(data: dict, path: tuple, value: str) -> None:
    """Set a nested dict value by tuple path."""
    obj = data
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


def _collect_candidates(data: dict, section_hint: str) -> list:
    """Return [(path_tuple, text), ...] scoped by section_hint."""
    hint = (section_hint or "").lower()
    candidates: list = []

    def _summary():
        if data.get("summary"):
            candidates.append((("summary",), data["summary"]))

    def _experience():
        for i, exp in enumerate(data.get("experience", [])):
            for j, b in enumerate(exp.get("bullets", [])):
                if b:
                    candidates.append((("experience", i, "bullets", j), b))

    def _projects():
        for i, p in enumerate(data.get("projects", [])):
            for j, b in enumerate(p.get("bullets", [])):
                if b:
                    candidates.append((("projects", i, "bullets", j), b))

    def _education():
        for i, ed in enumerate(data.get("education", [])):
            for j, d in enumerate(ed.get("details", [])):
                if d:
                    candidates.append((("education", i, "details", j), d))

    def _skills():
        for i, sk in enumerate(data.get("skills", [])):
            for j, s in enumerate(sk.get("skills", [])):
                if s:
                    candidates.append((("skills", i, "skills", j), s))

    def _certifications():
        for i, c in enumerate(data.get("certifications", [])):
            if c:
                candidates.append((("certifications", i), c))

    routines = {
        "summary": _summary,
        "experience": _experience,
        "projects": _projects,
        "education": _education,
        "skills": _skills,
        "certifications": _certifications,
    }
    if hint in routines:
        routines[hint]()
    else:
        for fn in routines.values():
            fn()
    return candidates


def _norm(text: str) -> str:
    """Lowercase + strip punctuation + collapse whitespace for fuzzy matching."""
    text = _PUNCT_RE.sub(' ', text.lower())
    return _SPACE_RE.sub(' ', text).strip()


def _apply_skill_mode(data: dict, sg: dict) -> int:
    """Handle Skills-section modes using the explicit-field schema.

    Returns 1 if applied, 0 otherwise."""
    mode = sg.get("mode", "")
    category = (sg.get("category") or "").strip()
    skill = (sg.get("skill") or "").strip()
    target_category = (sg.get("target_category") or "").strip()
    is_new_category = bool(sg.get("is_new_category"))
    data.setdefault("skills", [])

    if mode == "delete_category":
        target = category.lower()
        before = len(data["skills"])
        data["skills"] = [
            sk for sk in data["skills"]
            if (sk.get("category", "") or "").strip().lower() != target
        ]
        if len(data["skills"]) < before:
            logger.info("apply_suggestions: DELETE category %r", category)
            return 1
        return 0

    if mode == "remove_skill":
        if not category or not skill:
            return 0
        target_cat = category.lower()
        target_skill = skill.lower()
        for sk in data["skills"]:
            if (sk.get("category", "") or "").lower() != target_cat:
                continue
            before = len(sk.get("skills", []) or [])
            sk["skills"] = [
                s for s in (sk.get("skills", []) or [])
                if (s or "").strip().lower() != target_skill
            ]
            if len(sk["skills"]) < before:
                logger.info("apply_suggestions: REMOVE skill %r from %r", skill, category)
                return 1
            return 0
        return 0

    if mode == "rename_category":
        if not category or not target_category:
            return 0
        target = category.lower()
        for sk in data["skills"]:
            if (sk.get("category", "") or "").lower() == target:
                sk["category"] = target_category
                logger.info("apply_suggestions: RENAME category %r -> %r", category, target_category)
                return 1
        return 0

    if mode == "move_skill":
        if not category or not skill or not target_category:
            return 0
        src_cat = category.lower()
        dst_cat = target_category
        # Pull from source
        moved = False
        for sk in data["skills"]:
            if (sk.get("category", "") or "").lower() != src_cat:
                continue
            before = len(sk.get("skills", []) or [])
            sk["skills"] = [
                s for s in (sk.get("skills", []) or [])
                if (s or "").strip().lower() != skill.lower()
            ]
            moved = len(sk["skills"]) < before
            break
        if not moved:
            return 0
        # Push into destination
        dst_lower = dst_cat.lower()
        for sk in data["skills"]:
            if (sk.get("category", "") or "").lower() == dst_lower:
                sk.setdefault("skills", [])
                if skill.lower() not in {(x or "").strip().lower() for x in sk["skills"]}:
                    sk["skills"].append(skill)
                break
        else:
            data["skills"].append({"category": dst_cat, "skills": [skill]})
        logger.info("apply_suggestions: MOVE skill %r: %r -> %r", skill, category, dst_cat)
        return 1

    if mode == "add_skill":
        if not skill:
            return 0
        # Resolve destination category
        if is_new_category and target_category:
            dest_name = target_category
        elif category:
            dest_name = category
        elif target_category:
            dest_name = target_category
        else:
            dest_name = "Additional Skills"
        dest_lower = dest_name.lower()

        # Dedup: skip if skill already in destination
        existing = {
            (s or "").strip().lower()
            for cat in data["skills"]
            if (cat.get("category", "") or "").lower() == dest_lower
            for s in cat.get("skills", []) or [] if isinstance(s, str)
        }
        if skill.lower() in existing:
            logger.info("apply_suggestions: SKIP duplicate add %r in %r", skill, dest_name)
            return 0

        # Add to existing or create new category
        for sk in data["skills"]:
            if (sk.get("category", "") or "").lower() == dest_lower:
                sk.setdefault("skills", [])
                sk["skills"].append(skill)
                logger.info("apply_suggestions: ADD skill %r -> existing %r", skill, dest_name)
                return 1
        data["skills"].append({"category": dest_name, "skills": [skill]})
        logger.info("apply_suggestions: ADD new category %r with skill %r", dest_name, skill)
        return 1

    return 0


def apply_suggestions(resume: Resume, suggestions: list) -> Resume:
    """Apply tailoring suggestions (edits, adds, deletes) to resume.

    Skills section uses explicit fields: category, skill, target_category,
    is_new_category. Modes: add_skill, remove_skill, rename_category,
    delete_category, move_skill.

    Other sections use original/suggested with modes: replace, add_line,
    remove_line, replace_field, delete_project.

    Returns updated Resume object.
    """
    if not suggestions:
        return resume

    from rapidfuzz import fuzz, process as rf_process

    data = resume.model_dump()
    applied = 0

    for sg in suggestions:
        section = sg.get("section", "")
        mode = sg.get("mode", "replace")
        skill_section = section.lower().startswith("skill")

        # Skills section uses the explicit-field schema.
        if skill_section:
            applied += _apply_skill_mode(data, sg)
            continue

        original = (sg.get("original") or "").strip()
        suggested = (sg.get("suggested") or "").strip()
        prev = None
        while prev != suggested:
            prev = suggested
            suggested = _LEADING_BULLET_RE.sub('', suggested).strip()

        if not original:
            logger.debug("apply_suggestions: skip — empty original")
            continue
        if not suggested and mode not in ("remove_line", "delete_project"):
            logger.debug("apply_suggestions: skip — empty suggested for mode=%r", mode)
            continue

        # mode="delete_project" — remove an entire project entry by name.
        if mode == "delete_project":
            data.setdefault("projects", [])
            if not data["projects"]:
                continue
            target_name = original.strip().lower()
            before = len(data["projects"])
            data["projects"] = [
                p for p in data["projects"]
                if (p.get("name", "") or "").strip().lower() != target_name
            ]
            if len(data["projects"]) < before:
                applied += 1
                logger.info("apply_suggestions: DELETE project %r", original)
            else:
                # Fuzzy match as fallback
                match_result = rf_process.extractOne(
                    target_name, [p.get("name", "") for p in data["projects"]],
                    scorer=fuzz.partial_ratio, score_cutoff=55
                )
                if match_result:
                    matched_name, _score, idx = match_result
                    data["projects"].pop(idx)
                    applied += 1
                    logger.info("apply_suggestions: DELETE project (fuzzy) %r → %r", original, matched_name)
            continue

        # mode="remove_line" — delete one bullet/detail/cert.
        if mode == "remove_line":
            candidates = _collect_candidates(data, section)
            if not candidates:
                continue
            texts = [c[1] for c in candidates]
            norm_original = _norm(original)
            norm_texts = [_norm(t) for t in texts]
            result = rf_process.extractOne(
                norm_original, norm_texts, scorer=fuzz.partial_ratio, score_cutoff=55
            )
            if result is None:
                logger.warning("apply_suggestions: remove_line — no match for %r", original[:80])
                continue
            _matched_norm, _score, idx = result
            path = candidates[idx][0]
            if path[0] == "summary":
                data["summary"] = ""
                applied += 1
            elif len(path) == 4:
                parent_list_key = path[2]
                parent_idx = path[1]
                line_idx = path[3]
                parent = data[path[0]][parent_idx].get(parent_list_key) or []
                if 0 <= line_idx < len(parent):
                    parent.pop(line_idx)
                    applied += 1
                    logger.info("apply_suggestions: REMOVE_LINE %r from %s[%d].%s", original[:60], path[0], parent_idx, parent_list_key)
            elif path[0] == "certifications" and len(path) == 2:
                certs = data.get("certifications") or []
                if 0 <= path[1] < len(certs):
                    certs.pop(path[1])
                    applied += 1
                    logger.info("apply_suggestions: REMOVE_LINE cert %r", original[:60])
            continue

        # mode="replace_field" — overwrite a specific header field.
        if mode == "replace_field":
            parts = original.split("::")
            if len(parts) != 3:
                logger.warning("apply_suggestions: replace_field — bad original %r", original)
                continue
            sec_name, idx_str, field = parts
            try:
                entry_idx = int(idx_str)
            except ValueError:
                continue
            sec_key = {
                "experience": "experience", "projects": "projects",
                "education": "education", "contact": "contact",
            }.get(sec_name.lower())
            if not sec_key:
                continue
            if sec_key == "contact":
                data.setdefault("contact", {})[field] = suggested
                applied += 1
                logger.info("apply_suggestions: REPLACE_FIELD contact.%s", field)
                continue
            entries = data.get(sec_key) or []
            if 0 <= entry_idx < len(entries):
                entries[entry_idx][field] = suggested
                applied += 1
                logger.info("apply_suggestions: REPLACE_FIELD %s[%d].%s", sec_key, entry_idx, field)
            continue

        # mode="replace_bullets" — replace the entire bullets list for an entry.
        if mode == "replace_bullets":
            parts = original.split("::")
            if len(parts) == 2:
                sec_name, idx_str = parts
                try:
                    entry_idx = int(idx_str)
                    import json
                    new_bullets = json.loads(suggested)
                    if isinstance(new_bullets, list):
                        sec_key = sec_name.lower()
                        entries = data.get(sec_key) or []
                        if 0 <= entry_idx < len(entries):
                            entries[entry_idx]["bullets"] = new_bullets
                            applied += 1
                            logger.info("apply_suggestions: REPLACE_BULLETS %s[%d]", sec_key, entry_idx)
                except Exception as e:
                    logger.warning("apply_suggestions: replace_bullets parse failed: %s", e)
            continue

        # mode="add_line" — append a new bullet to an existing entry.
        if mode == "add_line":
            parts = original.split("::")
            if len(parts) != 2:
                continue
            sec_name, idx_str = parts
            try:
                entry_idx = int(idx_str)
            except ValueError:
                continue
            sec_lower = sec_name.lower()
            if sec_lower in ("experience", "projects", "education"):
                list_field = "details" if sec_lower == "education" else "bullets"
                entries = data.get(sec_lower) or []
                if 0 <= entry_idx < len(entries):
                    entries[entry_idx].setdefault(list_field, []).append(suggested)
                    applied += 1
                    logger.info("apply_suggestions: ADD_LINE %s[%d].%s", sec_lower, entry_idx, list_field)
            elif sec_lower in ("certifications", "certification"):
                data.setdefault("certifications", []).append(suggested)
                applied += 1
                logger.info("apply_suggestions: ADD_LINE certification")
            continue

        # Default mode="replace" — fuzzy match + substitute
        candidates = _collect_candidates(data, section)
        if not candidates:
            logger.warning("apply_suggestions: no candidates for section=%r  original=%r", section, original[:60])
            continue

        texts = [c[1] for c in candidates]
        norm_original = _norm(original)
        norm_texts = [_norm(t) for t in texts]
        result = rf_process.extractOne(
            norm_original, norm_texts, scorer=fuzz.partial_ratio, score_cutoff=55
        )
        if result is not None:
            matched_norm, score, idx = result
            logger.info("apply_suggestions: MATCH score=%d section=%r\n  original:  %r\n  matched:   %r\n  → applying: %r",
                       score, section, original[:80], texts[idx][:80], suggested[:80])
            _set_by_path(data, candidates[idx][0], suggested)
            applied += 1
        else:
            best = max((fuzz.partial_ratio(norm_original, t) for t in norm_texts), default=0)
            logger.warning("apply_suggestions: NO MATCH (best=%d < 55) section=%r\n  original: %r\n  top cand: %r",
                          best, section, original[:80], texts[0][:80] if texts else "")

    # Drop empty skill categories
    if isinstance(data.get("skills"), list):
        data["skills"] = [
            cat for cat in data["skills"]
            if (cat.get("skills") or [])
        ]

    logger.info("apply_suggestions: applied %d / %d suggestions", applied, len(suggestions))
    return Resume.model_validate(data)
