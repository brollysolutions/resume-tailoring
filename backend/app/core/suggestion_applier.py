"""Apply resume tailoring suggestions to Resume objects."""
import logging
import re
from typing import Optional
from app.models.resume_schema import Resume

logger = logging.getLogger(__name__)


def _note_unapplied(unapplied: Optional[list], sg: dict, reason: str) -> None:
    """Record a suggestion that could not be applied so callers can surface it
    instead of silently dropping the user's accepted edit. No-op when the caller
    passes no collector."""
    if unapplied is None:
        return
    unapplied.append({
        "section": sg.get("section", ""),
        "mode": sg.get("mode", "replace"),
        "original": (sg.get("original") or "")[:200],
        "reason": reason,
    })

_LEADING_BULLET_RE = re.compile(r"^\s*[-•*—‒–·]\s*")
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")

_ADDABLE_SECTIONS = {
    "experience", "education", "projects",
    "publications", "awards", "languages",
    "volunteer", "patents", "talks", "extra_sections",
    "certifications", "custom_links",
}

_SCALAR_REPLACE_SECTIONS = {
    "experience", "projects", "education",
    "publications", "awards", "languages",
    "volunteer", "patents", "talks", "extra_sections",
    "certifications", "custom_links",
}


def _blank_entry(section: str) -> dict:
    """Default-shaped entry for a list section. Mirrors frontend `_blankEntry`."""
    if section == "experience":
        return {"title": "", "company": "", "company_url": "", "location": "", "start_date": "", "end_date": "", "bullets": []}
    if section == "education":
        return {"institution": "", "degree": "", "field": "", "location": "", "start_date": "", "end_date": "", "gpa": "", "details": []}
    if section == "projects":
        return {"name": "", "tech": "", "date": "", "url": "", "demo_url": "", "bullets": []}
    if section == "publications":
        return {"title": "New publication", "authors": "", "venue": "", "year": "", "doi": "", "url": ""}
    if section == "awards":
        return {"title": "New award", "issuer": "", "date": "", "description": ""}
    if section == "languages":
        return {"name": "New language", "proficiency": ""}
    if section == "volunteer":
        return {"role": "New role", "organization": "", "location": "", "start_date": "", "end_date": "", "bullets": []}
    if section == "patents":
        return {"title": "New patent", "number": "", "date": "", "status": "", "authors": ""}
    if section == "talks":
        return {"title": "New talk", "venue": "", "date": "", "type": ""}
    if section == "certifications":
        return {"name": "New certification", "issuer": "", "date": "", "credential_url": ""}
    if section == "custom_links":
        return {"label": "Link", "url": ""}
    if section == "extra_sections":
        return {"title": "New Section", "content_type": "entries", "items": []}
    return {}


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
            if c and isinstance(c, dict):
                name = c.get("name")
                if name:
                    candidates.append((("certifications", i, "name"), name))
            elif isinstance(c, str):
                candidates.append((("certifications", i), c))

    def _volunteer():
        for i, v in enumerate(data.get("volunteer", [])):
            for j, b in enumerate(v.get("bullets", [])):
                if b:
                    candidates.append((("volunteer", i, "bullets", j), b))

    def _extra_sections():
        for i, xs in enumerate(data.get("extra_sections", [])):
            for j, item in enumerate(xs.get("items", []) or []):
                for k, b in enumerate(item.get("bullets", []) or []):
                    if b:
                        candidates.append((("extra_sections", i, "items", j, "bullets", k), b))
                t = item.get("text")
                if t:
                    candidates.append((("extra_sections", i, "items", j, "text"), t))

    routines = {
        "summary": _summary,
        "experience": _experience,
        "projects": _projects,
        "education": _education,
        "skills": _skills,
        "certifications": _certifications,
        "volunteer": _volunteer,
        "extra_sections": _extra_sections,
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

    if mode == "replace_section":
        new_skills = sg.get("new_skills", [])
        if isinstance(new_skills, list):
            data["skills"] = list(new_skills)
            logger.info("apply_suggestions: REPLACE_SECTION skills (count=%d)", len(data["skills"]))
            return 1
        else:
            logger.warning("apply_suggestions: replace_section failed — new_skills is not a list: %r", type(new_skills))
        return 0

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


def resolve_verbatim_original(resume_data: dict, section: str, original: str) -> str | None:
    """Snap an LLM-provided `original` to the exact resume line it refers to.

    The chat copilot's `original` can be a paraphrase (the model echoes the line
    imperfectly). The backend applier matches fuzzily so it still applies, but the
    client-side applier matches exactly and would miss — leaving the editor panel
    out of sync with the preview. Returning the verbatim line lets both appliers
    act on the identical string. Returns None when no candidate clears the bar.
    """
    if not original:
        return None
    from rapidfuzz import fuzz, process as rf_process

    candidates = _collect_candidates(resume_data, section)
    if not candidates:
        return None
    texts = [c[1] for c in candidates]
    norm_texts = [_norm(t) for t in texts]
    result = rf_process.extractOne(
        _norm(original), norm_texts, scorer=fuzz.partial_ratio, score_cutoff=55
    )
    if result is None:
        return None
    _matched_norm, _score, idx = result
    return texts[idx]


def apply_suggestions(resume: Resume, suggestions: list, unapplied: Optional[list] = None) -> Resume:
    """Apply tailoring suggestions (edits, adds, deletes) to resume.

    Skills section uses explicit fields: category, skill, target_category,
    is_new_category. Modes: add_skill, remove_skill, rename_category,
    delete_category, move_skill.

    Other sections use original/suggested with modes: replace, add_line,
    remove_line, replace_field, delete_project.

    If `unapplied` (a list) is provided, suggestions that could not be applied
    (no fuzzy match, no candidate lines, malformed) are appended to it as
    {section, mode, original, reason} so the caller can surface them instead of
    dropping the user's accepted edit silently. Returns updated Resume object.
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

        # mode="add_entry" — append a (blank or seeded) entry to a list section.
        if mode == "add_entry":
            sec_name = (sg.get("original") or "").strip().lower()
            if sec_name not in _ADDABLE_SECTIONS:
                logger.warning("apply_suggestions: add_entry — unknown section %r", sec_name)
                continue
            initial_json = sg.get("suggested") or ""
            initial: dict = {}
            if initial_json.strip() and initial_json.strip() != "{}":
                try:
                    import json
                    parsed = json.loads(initial_json)
                    if isinstance(parsed, dict):
                        initial = parsed
                except Exception:
                    initial = {}
            entry = {**_blank_entry(sec_name), **initial}
            data.setdefault(sec_name, []).append(entry)
            applied += 1
            logger.info("apply_suggestions: ADD_ENTRY %s (idx=%d)", sec_name, len(data[sec_name]) - 1)
            # ExtraSections render via `extra:<title>` keys in section_order. Inject one so the new entry shows up.
            if sec_name == "extra_sections":
                title = (entry.get("title") or "New Section").strip()
                tag = f"extra:{title}"
                order = list(data.get("section_order") or [])
                if tag not in order:
                    order.append(tag)
                    data["section_order"] = order
            continue

        # mode="delete_entry" — remove an entry by index from a list section.
        if mode == "delete_entry":
            parts = (sg.get("original") or "").split("::")
            if len(parts) != 2:
                logger.warning("apply_suggestions: delete_entry — bad original %r", sg.get("original"))
                continue
            sec_name, idx_str = parts[0].strip().lower(), parts[1].strip()
            if sec_name not in _ADDABLE_SECTIONS:
                continue
            try:
                entry_idx = int(idx_str)
            except ValueError:
                continue
            entries = data.get(sec_name) or []
            if 0 <= entry_idx < len(entries):
                entries.pop(entry_idx)
                applied += 1
                logger.info("apply_suggestions: DELETE_ENTRY %s[%d]", sec_name, entry_idx)
            continue

        # mode="toggle_hidden" — add/remove a section name from hidden_sections.
        if mode == "toggle_hidden":
            sec_name = (sg.get("original") or "").strip().lower()
            action = (sg.get("suggested") or "").strip().lower()
            if not sec_name:
                continue
            hidden = data.setdefault("hidden_sections", [])
            has = sec_name in hidden
            if action == "hide" and not has:
                hidden.append(sec_name)
                applied += 1
            elif action == "show" and has:
                data["hidden_sections"] = [s for s in hidden if s != sec_name]
                applied += 1
            elif action == "toggle":
                data["hidden_sections"] = [s for s in hidden if s != sec_name] if has else hidden + [sec_name]
                applied += 1
            logger.info("apply_suggestions: TOGGLE_HIDDEN %s -> %s", sec_name, action)
            continue

        # mode="reorder_sections" — update the global section order.
        if mode == "reorder_sections":
            try:
                import json
                new_order = json.loads(sg.get("suggested") or "")
                if isinstance(new_order, list):
                    data["section_order"] = new_order
                    applied += 1
                    logger.info("apply_suggestions: REORDER_SECTIONS (count=%d)", len(new_order))
            except Exception as e:
                logger.warning("apply_suggestions: reorder_sections parse failed: %s", e)
            continue

        # mode="set_summary" — create summary from scratch (no existing text to match).
        if mode == "set_summary":
            suggested_text = (sg.get("suggested") or "").strip()
            if suggested_text:
                data["summary"] = suggested_text
                applied += 1
                logger.info("apply_suggestions: SET_SUMMARY (len=%d)", len(suggested_text))
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
                else:
                    _note_unapplied(unapplied, sg, "delete_project: no project name matched")
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
                _note_unapplied(unapplied, sg, "remove_line: no matching line found")
                continue
            _matched_norm, _score, idx = result
            path = candidates[idx][0]
            if path[0] == "summary":
                data["summary"] = ""
                applied += 1
            elif path[0] == "extra_sections" and len(path) == 6:
                # ("extra_sections", i, "items", j, "bullets", k)
                _, i, _, j, _, k = path
                items = (data.get("extra_sections") or [])
                if 0 <= i < len(items):
                    it = (items[i].get("items") or [])
                    if 0 <= j < len(it):
                        bl = (it[j].get("bullets") or [])
                        if 0 <= k < len(bl):
                            bl.pop(k)
                            applied += 1
                            logger.info("apply_suggestions: REMOVE_LINE extra_sections[%d].items[%d].bullets[%d]", i, j, k)
            elif path[0] == "extra_sections" and len(path) == 5 and path[-1] == "text":
                # ("extra_sections", i, "items", j, "text")
                _, i, _, j, _ = path
                items = (data.get("extra_sections") or [])
                if 0 <= i < len(items):
                    it = (items[i].get("items") or [])
                    if 0 <= j < len(it):
                        it[j]["text"] = ""
                        applied += 1
                        logger.info("apply_suggestions: REMOVE_LINE extra_sections[%d].items[%d].text", i, j)
            elif len(path) == 4:
                parent_list_key = path[2]
                parent_idx = path[1]
                line_idx = path[3]
                parent = data[path[0]][parent_idx].get(parent_list_key) or []
                if 0 <= line_idx < len(parent):
                    parent.pop(line_idx)
                    applied += 1
                    logger.info("apply_suggestions: REMOVE_LINE %r from %s[%d].%s", original[:60], path[0], parent_idx, parent_list_key)
            elif path[0] == "certifications" and len(path) == 3:
                # ("certifications", i, "name")
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
            sec_lower = sec_name.lower()

            # Guard URL fields from LLM tailoring
            if field.endswith("_url") or field in {"linkedin", "github", "website", "doi", "url"}:
                logger.warning("apply_suggestions: GUARDED field %r from replace_field", field)
                continue

            if sec_lower == "contact":
                data.setdefault("contact", {})[field] = suggested
                applied += 1
                logger.info("apply_suggestions: REPLACE_FIELD contact.%s", field)
                continue
            if sec_lower == "resume":
                # Top-level scalar on Resume (e.g. name).
                data[field] = suggested
                applied += 1
                logger.info("apply_suggestions: REPLACE_FIELD resume.%s", field)
                continue
            if sec_lower not in _SCALAR_REPLACE_SECTIONS:
                continue
            try:
                entry_idx = int(idx_str)
            except ValueError:
                continue
            entries = data.get(sec_lower) or []
            if 0 <= entry_idx < len(entries):
                entries[entry_idx][field] = suggested
                applied += 1
                logger.info("apply_suggestions: REPLACE_FIELD %s[%d].%s", sec_lower, entry_idx, field)
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
            if sec_lower in ("experience", "projects", "education", "volunteer"):
                list_field = "details" if sec_lower == "education" else "bullets"
                entries = data.get(sec_lower) or []
                if 0 <= entry_idx < len(entries):
                    entries[entry_idx].setdefault(list_field, []).append(suggested)
                    applied += 1
                    logger.info("apply_suggestions: ADD_LINE %s[%d].%s", sec_lower, entry_idx, list_field)
            elif sec_lower in ("certifications", "certification"):
                # Seed a structured certification
                data.setdefault("certifications", []).append({"name": suggested})
                applied += 1
                logger.info("apply_suggestions: ADD_LINE certification")
            continue

        # Default mode="replace" — fuzzy match + substitute
        candidates = _collect_candidates(data, section)
        if not candidates:
            logger.warning("apply_suggestions: no candidates for section=%r  original=%r", section, original[:60])
            _note_unapplied(unapplied, sg, f"no candidate lines in section {section!r}")
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
            _note_unapplied(unapplied, sg, f"no resume line matched original (best fuzzy {best} < 55)")

    # Note: We used to drop empty skill categories here, but that is now
    # handled by the Pydantic validator/model itself or intentionally kept
    # for user review.

    logger.info("apply_suggestions: applied %d / %d suggestions", applied, len(suggestions))
    return Resume.model_validate(data)
