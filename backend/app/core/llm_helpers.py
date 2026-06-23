"""Resume section tailoring: extract/generate/tailor operations."""
import json
import logging
import re
from typing import List, Optional
from app.core.llm_client import _chat, get_smart_model, get_model_name
from app.core.llm_prompts import (
    PROMPT_TAILOR_SUMMARY_SYSTEM as PROMPT_TAILOR_SUMMARY,
    PROMPT_GENERATE_SUMMARY_SYSTEM as PROMPT_GENERATE_SUMMARY,
    PROMPT_TAILOR_EXPERIENCE_SYSTEM as PROMPT_TAILOR_EXPERIENCE,
    PROMPT_TAILOR_PROJECTS_SYSTEM as PROMPT_TAILOR_PROJECTS,
    PROMPT_TAILOR_SKILLS_SYSTEM as PROMPT_TAILOR_SKILLS,
    PROMPT_TAILOR_EDUCATION_SYSTEM as PROMPT_TAILOR_EDUCATION,
    PROMPT_PREPROCESS_JD_SYSTEM as PROMPT_PREPROCESS_JD,
    PROMPT_EXTRACT_JD_HARD_REQUIREMENTS_SYSTEM as PROMPT_EXTRACT_JD_HARD_REQUIREMENTS,
    PROMPT_SECTION_DIAGNOSIS_SYSTEM,
    PROMPT_MATCH_BLOCKERS_SYSTEM,
    PROMPT_GENERATE_SKILLS_GOLDMINE_SYSTEM,
    ANTI_GRAFT_CLAUSE,
    INTENSITY_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)

# Clean suggested text: remove bullets, labels, JD commentary
_LEADING_MARKER_RE = re.compile(r'^\s*(?:[-•*—‒–·]+|\d+[.)])\s+')
_JD_PAREN_RE = re.compile(r'\s*\([^)]*\b(?:JD|Job Description|job description)\b[^)]*\)', re.IGNORECASE)
_INLINE_DASH_RE = re.compile(r'\s*[–—]\s*|\s+-\s+')
_COMPOUND_HYPHEN_RE = re.compile(r'(?<=\w)-(?=\w)')
_LABEL_PREFIX_RE = re.compile(r'^\s*(?:[SBM]\d+|Suggested|Original|New|Bullet)\s*:\s*', re.IGNORECASE)

_META_PHRASES = [
    r"aligns\s+with",
    r"job\s+description",
    r"jd['’]?s?\s+requirement",
    r"this\s+experience",
    r"this\s+bullet",
    r"suggested\s+to\s+include",
    r"demonstrates\s+.*?\s+which\s+aligns",
    r"supports\s+jd",
]
_META_RE = re.compile("|".join(_META_PHRASES), re.IGNORECASE)


def _looks_like_meta(text: str) -> bool:
    """Check if the text contains metalanguage/commentary about JD alignment."""
    if not text:
        return False
    return bool(_META_RE.search(text))


_GRAFT_FIRST_PERSON_RE = re.compile(r"\b(I|me|my|we|our)\b", re.IGNORECASE)
_GRAFT_GERUND_RE = re.compile(r"^\s*\w+ing\b[^,]{0,80},\s", re.IGNORECASE)


def _looks_like_graft(text: str) -> bool:
    """True if first person pronouns exist or starts with a gerund-clause opener like 'Using ...,', 'Improving ...,'."""
    if not text:
        return False
    if _GRAFT_FIRST_PERSON_RE.search(text):
        return True
    if _GRAFT_GERUND_RE.match(text):
        return True
    return False


def _clean_suggested(text: str) -> str:
    """Strip leading markers, labels, and JD commentary from suggested text."""
    if not text:
        return text
    prev = None
    while prev != text:
        prev = text
        text = _LEADING_MARKER_RE.sub('', text)
        text = _LABEL_PREFIX_RE.sub('', text)
    text = _JD_PAREN_RE.sub('', text)
    text = _INLINE_DASH_RE.sub(' ', text)
    text = _COMPOUND_HYPHEN_RE.sub(' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _keyword_injection_block(keywords: list, intensity: str = "balanced") -> str:
    """Returns prompt appendix for keyword injection, or empty string."""
    if not keywords:
        return ""
    
    if intensity == "light":
        prefix = "only if it already fits, never add a new claim:\n"
    elif intensity == "aggressive":
        prefix = "inject every keyword honestly claimable:\n"
    else:
        prefix = "weave each into existing content where honestly applicable:\n"

    return (
        "\n\nMISSING JD KEYWORDS — absent from resume, weighed heavily by match score. "
        + prefix
        + ", ".join(keywords[:20])
    )


async def _tailor_section(system_prompt: str, user_content: str, cap: int, model: str | None = None, reject_first_person: bool = False) -> list:
    """Shared LLM call + clean + cap for all section tailors."""
    try:
        content = await _chat(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_content}],
            json_mode=True,
            model=model,
        )
        parsed = json.loads(content)
        suggestions = parsed.get("suggestions", [])
    except Exception as e:
        logger.warning(f"[tailor_section] json_mode failed, retrying: {e}")
        try:
            content = await _chat(
                [{"role": "system", "content": system_prompt + "\nRespond ONLY with valid JSON."},
                 {"role": "user", "content": user_content}],
                json_mode=False,
                model=model,
            )
            start = content.find("{"); end = content.rfind("}") + 1
            suggestions = json.loads(content[start:end]).get("suggestions", []) if start != -1 and end > 0 else []
        except Exception:
            return []

    cleaned = []
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        s["suggested"] = _clean_suggested(s.get("suggested", ""))
        if not s.get("suggested") and s.get("mode") != "remove_line":
            continue
        if s.get("mode") == "add_line":
            continue
        if _looks_like_meta(s["suggested"]):
            continue
        if reject_first_person and _looks_like_graft(s["suggested"]):
            continue
        cleaned.append(s)
    return cleaned[:cap]


async def generate_keywords(text: str, max_keywords: int = 5) -> tuple[list[str], list[str]]:
    """
    Extract standard industry job titles and core technology tokens from resume text.
    Returns (roles, core_stack).
    """
    from app.core.llm_prompts import PROMPT_GENERATE_KEYWORDS_USER
    try:
        prompt = PROMPT_GENERATE_KEYWORDS_USER.format(text=text[:4000])
        content = await _chat([{"role": "user", "content": prompt}], json_mode=True)
        parsed = json.loads(content)
        raw_roles = parsed.get("roles", [])
        raw_stack = parsed.get("core_stack", [])

        # Ensure we have clean, unique lists while preserving order
        roles = []
        seen_roles = set()
        for r in raw_roles:
            if isinstance(r, str) and r.strip():
                clean_r = r.strip()
                lower_r = clean_r.lower()
                if lower_r not in seen_roles:
                    seen_roles.add(lower_r)
                    roles.append(clean_r)
        roles = roles[:max_keywords]

        stack = []
        seen_stack = set()
        for s in raw_stack:
            if isinstance(s, str) and s.strip():
                clean_s = s.strip()
                lower_s = clean_s.lower()
                if lower_s not in seen_stack:
                    seen_stack.add(lower_s)
                    stack.append(clean_s)

        if not roles:
            roles = ["Software Engineer", "Developer"]

        return roles, stack
    except Exception as e:
        logger.warning(f"generate_keywords failed: {e}")
        return ["Software Engineer", "Developer"], []



async def tailor_education(
    education: list,
    jd_text: str,
    keywords_to_inject: Optional[list] = None,
    intensity: str = "balanced",
) -> list:
    """Tailor Education details (not headers) to match JD."""
    if not education:
        return []

    lines = []
    has_any_details = False
    for i, ed in enumerate(education):
        head = (ed.get("degree") or "") + (f" in {ed.get('field')}" if ed.get("field") else "")
        head = head.strip() or "(degree)"
        inst = ed.get("institution") or "(institution)"
        lines.append(f"E{i} — {head} @ {inst}")
        for j, d in enumerate(ed.get("details") or []):
            if d:
                lines.append(f"  D{i}.{j}: {d}")
                has_any_details = True
    if not has_any_details:
        return []

    system = PROMPT_TAILOR_EDUCATION + INTENSITY_INSTRUCTIONS[intensity] + _keyword_injection_block(keywords_to_inject or [], intensity)
    user = (
        "EDUCATION ENTRIES + DETAIL LINES:\n"
        + "\n".join(lines)
        + f"\n\nJOB DESCRIPTION:\n{jd_text[:2000]}"
    )
    sugg = await _tailor_section(system, user, cap=6, model=get_smart_model(), reject_first_person=False)
    for s in sugg:
        s["section"] = "Education"
        s.setdefault("mode", "replace")
    return sugg


async def tailor_summary(
    summary: Optional[str],
    jd_text: str,
    keywords_to_inject: Optional[list] = None,
    intensity: str = "balanced",
) -> list:
    """Tailor summary to match JD (0–1 suggestion)."""
    if not summary or not summary.strip():
        return []

    system = PROMPT_TAILOR_SUMMARY + INTENSITY_INSTRUCTIONS[intensity] + _keyword_injection_block(keywords_to_inject or [], intensity)
    user = (
        f"CURRENT SUMMARY:\n{summary}\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:2000]}"
    )
    return await _tailor_section(system, user, cap=1, model=get_smart_model(), reject_first_person=False)


async def generate_summary(
    resume_context: str,
    jd_text: str,
    keywords_to_inject: Optional[list] = None,
    intensity: str = "balanced",
) -> list:
    """Generate a summary from scratch when the resume has none."""
    system = PROMPT_GENERATE_SUMMARY + INTENSITY_INSTRUCTIONS[intensity] + _keyword_injection_block(keywords_to_inject or [], intensity)
    user = (
        f"CANDIDATE BACKGROUND:\n{resume_context}\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:2000]}"
    )
    sugg = await _tailor_section(system, user, cap=1, model=get_smart_model(), reject_first_person=False)
    for s in sugg:
        s["section"] = "Summary"
        s["mode"] = "set_summary"
        s.setdefault("original", "")
    return sugg


async def tailor_experience(
    experience: list,
    jd_text: str,
    keywords_to_inject: Optional[list] = None,
    intensity: str = "balanced",
) -> list:
    """Tailor experience bullets (3–8 suggestions)."""
    if not experience:
        return []

    lines = []
    for i, exp in enumerate(experience):
        sd = exp.get("start_date") or ""
        ed = exp.get("end_date") or "Present"
        dates = f"{sd} – {ed}".strip(" –")
        lines.append(f"[{i+1}] {exp.get('title','')} @ {exp.get('company','')}  ({dates})")
        for j, b in enumerate(exp.get("bullets", [])):
            lines.append(f"  B{j+1}: {b}")

    system = PROMPT_TAILOR_EXPERIENCE + ANTI_GRAFT_CLAUSE + INTENSITY_INSTRUCTIONS[intensity] + _keyword_injection_block(keywords_to_inject or [], intensity)
    user = (
        f"EXPERIENCE:\n{chr(10).join(lines)}\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:2000]}"
    )

    cap_val = {"light": 3, "balanced": 6, "aggressive": 8}.get(intensity, 6)
    raw_suggestions = await _tailor_section(system, user, cap=cap_val, model=get_smart_model(), reject_first_person=True)

    # Deduplicate by original bullet
    seen = set()
    deduped = []
    for s in raw_suggestions:
        orig = s.get("original", "").strip()
        if orig not in seen:
            seen.add(orig)
            deduped.append(s)
    return deduped


async def tailor_projects(
    projects: list,
    jd_text: str,
    keywords_to_inject: Optional[list] = None,
    intensity: str = "balanced",
) -> list:
    """Tailor project bullets with project_index tags."""
    if not projects:
        return []

    from rapidfuzz import fuzz

    lines = []
    for i, proj in enumerate(projects):
        tech = proj.get("tech") or ""
        header = f"[project_index={i}] {proj.get('name','')}" + (f" ({tech})" if tech else "")
        lines.append(header)
        for j, b in enumerate(proj.get("bullets", [])):
            lines.append(f"  B{j+1}: {b}")

    system = PROMPT_TAILOR_PROJECTS + ANTI_GRAFT_CLAUSE + INTENSITY_INSTRUCTIONS[intensity] + _keyword_injection_block(keywords_to_inject or [], intensity)
    user = (
        f"PROJECTS:\n{chr(10).join(lines)}\n\n"
        f"JOB DESCRIPTION:\n{jd_text[:2000]}"
    )
    suggestions = await _tailor_section(system, user, cap=20, model=get_smart_model(), reject_first_person=True)

    # Validate / repair project_index
    n_projects = len(projects)
    for s in suggestions:
        idx = s.get("project_index")
        if isinstance(idx, int) and 0 <= idx < n_projects:
            continue
        # Repair: fuzzy-match original to project bullets
        original = s.get("original", "")
        best_i, best_score = 0, -1
        for i, proj in enumerate(projects):
            for b in proj.get("bullets", []):
                score = fuzz.partial_ratio(original, b)
                if score > best_score:
                    best_score, best_i = score, i
        s["project_index"] = best_i

    return suggestions


async def _llm_filter_skill_suggestions(
    add_skill_suggs: list,
    jd_text: str,
    experience_ctx: str,
    projects_ctx: str,
) -> list:
    """Contextual LLM gate for add_skill suggestions.

    Three gates — ALL must pass for a suggestion to survive:
    1. REAL NAMED SKILL — specific technology/tool/language/library/framework/platform.
       Rejects concept nouns, role titles, common English words, credentials.
    2. GROUNDED — evidence of the skill appears in the candidate's background.
    3. JD-RELEVANT — JD meaningfully requires it, not just boilerplate mention.

    Falls back to the full list on any error so skills are never silently lost.
    Uses fast model + cache (mirrors _llm_filter_actionable_keywords in ats_simulator).
    """
    if not add_skill_suggs:
        return add_skill_suggs

    items = "\n".join(
        f"{i}. skill={s.get('skill')!r} → category={((s.get('category') or s.get('target_category')) or 'NEW')!r}"
        for i, s in enumerate(add_skill_suggs)
    )
    background = "\n".join(filter(None, [experience_ctx, projects_ctx]))

    prompt = (
        "You are a resume skill validator. Keep ONLY additions that pass ALL THREE gates.\n\n"
        "GATE 1 — REAL NAMED SKILL: Must be a specific, named technology, tool, language, "
        "library, framework, or platform. REJECT: concept nouns (e.g. 'Data Storage', "
        "'System Design', 'Information Retrieval'), role titles ('Full Stack Development'), "
        "common English words ('list', 'science', 're', 'law', 'set', 'code'), "
        "EEO/legal terms ('accessible', 'accessibility'), education credentials "
        "('Bachelor\\'s', 'degree', 'master\\'s', 'PhD').\n\n"
        "GATE 2 — GROUNDED: The skill or close evidence of it must appear in the "
        "candidate's background. Do NOT add skills visible only in the JD.\n\n"
        "GATE 3 — JD-RELEVANT: The JD must meaningfully call for this skill, "
        "not just mention it incidentally or in boilerplate.\n\n"
        f"CANDIDATE BACKGROUND:\n<BACKGROUND>\n{background[:1000]}\n</BACKGROUND>\n\n"
        f"JOB DESCRIPTION:\n<JD>\n{jd_text[:800]}\n</JD>\n\n"
        f"PROPOSED SKILL ADDITIONS:\n{items}\n\n"
        'Return ONLY JSON: {"keep": [list of integer indices that pass all three gates]}'
    )

    try:
        raw = await _chat(
            [{"role": "user", "content": prompt}],
            json_mode=True,
            model=get_model_name(),
            use_cache=True,
        )
        result = json.loads(raw)
        keep_indices = result.get("keep", list(range(len(add_skill_suggs))))
        valid_indices = {i for i in keep_indices if isinstance(i, int) and 0 <= i < len(add_skill_suggs)}
        filtered = [s for i, s in enumerate(add_skill_suggs) if i in valid_indices]
        dropped = len(add_skill_suggs) - len(filtered)
        if dropped:
            logger.info("[tailor_skills] LLM filter dropped %d add_skill suggestion(s)", dropped)
        return filtered
    except Exception as e:
        logger.warning("[tailor_skills] LLM filter failed (%s) — returning unfiltered", e)
        return add_skill_suggs


async def tailor_skills(
    skills: list,
    jd_text: str,
    keywords_to_inject: Optional[list] = None,
    experience_ctx: str = "",
    projects_ctx: str = "",
    certifications_ctx: str = "",
    user_prompt: Optional[str] = None,
    intensity: str = "balanced",
) -> list:
    """Tailor skills with add/delete modes grounded in evidence."""
    if not skills:
        return []

    lines = [f"{sk.get('category','')}: {', '.join(sk.get('skills', []))}" for sk in skills]
    categories = [sk.get("category", "") for sk in skills]
    cats_listing = ", ".join(categories) if categories else "(none)"

    system = PROMPT_TAILOR_SKILLS + INTENSITY_INSTRUCTIONS[intensity]

    user_parts = []
    if user_prompt and user_prompt.strip():
        user_parts.append(
            "USER INSTRUCTION (honor where consistent with JD coverage):\n"
            + user_prompt.strip()[:500]
        )
    if experience_ctx:
        user_parts.append(f"EXPERIENCE EVIDENCE:\n{experience_ctx[:600]}")
    if projects_ctx:
        user_parts.append(f"PROJECT EVIDENCE:\n{projects_ctx[:600]}")
    if certifications_ctx:
        user_parts.append(f"CERTIFICATIONS:\n{certifications_ctx[:300]}")
    user_parts.append(f"SKILLS:\n{chr(10).join(lines)}")

    all_skills_flat = sorted({(s or "").strip() for sk in skills for s in sk.get("skills", []) if (s or "").strip()},
                             key=lambda x: x.lower())
    if all_skills_flat:
        user_parts.append(
            "ALL EXISTING SKILLS (never add these):\n"
            + ", ".join(all_skills_flat)
        )
    user_parts.append(f"JOB DESCRIPTION:\n{jd_text[:1500]}")

    if keywords_to_inject:
        user_parts.append(
            "MISSING JD SKILLS — add any with evidence:\n"
            + ", ".join(keywords_to_inject[:30])
        )

    user = "\n\n".join(user_parts)
    try:
        content = await _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            json_mode=True,
            model=get_smart_model(),
        )
        suggestions = json.loads(content).get("suggestions", [])
    except Exception as e:
        logger.warning("[tailor_skills] LLM call failed: %s", e)
        try:
            content = await _chat(
                [{"role": "system", "content": system + "\nRespond ONLY with valid JSON."},
                 {"role": "user", "content": user}],
                json_mode=False,
                model=get_smart_model(),
            )
            start, end = content.find("{"), content.rfind("}") + 1
            suggestions = json.loads(content[start:end]).get("suggestions", []) if start != -1 and end > 0 else []
        except Exception:
            return []
    if not isinstance(suggestions, list):
        return []

    # Validate the new explicit-field schema. Modes:
    #   add_skill        — needs skill + (category OR (target_category + is_new_category))
    #   remove_skill     — needs category + skill
    #   rename_category  — needs category + target_category
    #   delete_category  — needs category (cap at 2 deletions)
    #   move_skill       — needs category + skill + target_category
    _EDU_CREDENTIALS = frozenset({
        "bachelor", "bachelor's", "bachelors", "master", "master's", "masters",
        "phd", "ph.d", "doctorate", "doctoral", "undergraduate", "graduate",
        "postgraduate", "mba", "degree", "diploma",
    })

    cats_lower = {c.lower() for c in categories}
    cleaned: list = []
    delete_count = 0
    for s in suggestions:
        s["section"] = "Skills"
        mode = (s.get("mode") or "").strip()
        category = (s.get("category") or "").strip()
        skill = (s.get("skill") or "").strip()
        target_category = (s.get("target_category") or "").strip()
        is_new_category = bool(s.get("is_new_category"))

        # Drop add_skill with trivially short or obviously-non-skill strings.
        # Allowlist keeps single-char/short langs: C, R, Go, SQL, Git, etc.
        _SHORT_SKILL_ALLOWLIST = {
            "c", "r", "go", "sql", "git", "aws", "gcp", "lua", "vim",
            "c#", "c++", "ai", "ml", "ui", "ux", "qa",
        }
        _COMMON_WORD_BLOCKLIST = {
            "science", "list", "set", "map", "type", "class", "object",
            "function", "method", "variable", "re", "new", "old", "big",
            "small", "basic", "general", "advanced", "core", "main",
            "key", "top", "best", "good", "high", "low", "fast", "slow",
            "large", "real", "open", "free", "data", "code", "work",
            "test", "build", "run", "use", "get", "put", "add", "update",
            "create", "read", "write", "load", "save", "send", "receive",
        }
        if mode == "add_skill" and skill:
            skill_lower = skill.lower()
            if skill_lower in _COMMON_WORD_BLOCKLIST:
                logger.warning("[tailor_skills] dropping common-word skill: '%s'", skill)
                continue
            if len(skill) <= 2 and skill_lower not in _SHORT_SKILL_ALLOWLIST:
                logger.warning("[tailor_skills] dropping too-short skill: '%s'", skill)
                continue

        # Drop add_skill where the skill IS the category name (e.g. "security" → "Security")
        if mode == "add_skill" and skill:
            dest = (category or target_category).lower()
            if skill.lower() == dest:
                logger.warning("[tailor_skills] dropping: skill '%s' == category name", skill)
                continue

        # Drop add_skill for education credentials (e.g. "Bachelor's degree")
        if mode == "add_skill" and skill:
            skill_words = set(skill.lower().replace("'s", "").replace("'", "").split())
            if skill_words & _EDU_CREDENTIALS:
                logger.warning("[tailor_skills] dropping education credential as skill: '%s'", skill)
                continue

        # Drop add_skill for role-concept phrases — vague nouns that aren't tools
        # e.g. "Full Stack Development", "Data Storage", "System Design"
        _CONCEPT_SUFFIXES = {"development", "engineering", "management", "storage",
                             "design", "architecture", "operations", "administration",
                             "technologies", "technology", "solutions", "services",
                             "systems", "infrastructure", "methodology", "practices",
                             "retrieval", "processing", "computation", "inference",
                             "analysis", "analytics", "modeling", "modelling"}
        if mode == "add_skill" and skill:
            last_word = skill.lower().rsplit(None, 1)[-1]
            if last_word in _CONCEPT_SUFFIXES and len(skill.split()) >= 2:
                logger.warning("[tailor_skills] dropping concept-noun skill: '%s'", skill)
                continue

        if mode == "delete_category":
            if category.lower() not in cats_lower:
                continue
            if delete_count >= 2:
                continue
            delete_count += 1
            cleaned.append(s)
            continue

        if mode == "remove_skill":
            if not category or not skill:
                continue
            if category.lower() not in cats_lower:
                continue
            cleaned.append(s)
            continue

        if mode == "rename_category":
            if not category or not target_category:
                continue
            if category.lower() not in cats_lower:
                continue
            cleaned.append(s)
            continue

        if mode == "move_skill":
            if not category or not skill or not target_category:
                continue
            if category.lower() not in cats_lower:
                continue
            # is_new_category defaults False unless target already missing
            if not is_new_category and target_category.lower() not in cats_lower:
                s["is_new_category"] = True
            cleaned.append(s)
            continue

        if mode == "add_skill":
            if not skill:
                continue
            # Must target either an existing category or a new one
            if category and category.lower() in cats_lower:
                s["is_new_category"] = False
                cleaned.append(s)
                continue
            if target_category:
                s["is_new_category"] = True
                cleaned.append(s)
                continue
            # Fallback: synthesize a new category from whatever the model gave
            fallback = category or "Additional Skills"
            s["category"] = ""
            s["target_category"] = fallback
            s["is_new_category"] = True
            cleaned.append(s)
            continue

    # Taxonomy validation
    from app.core import skill_taxonomy as _tax

    # Collapse new categories that overlap an existing one's domain hints.
    # Example: model proposes target_category="Cloud & Backend" + is_new_category=True
    # but an existing "Backend & Engineering" already covers that domain — reroute
    # the add into the existing category.
    for s in cleaned:
        if s.get("mode") != "add_skill":
            continue
        if not s.get("is_new_category"):
            continue
        target = (s.get("target_category") or "").strip()
        if not target:
            continue
        covered = _tax.existing_covering_category(target, categories)
        if covered and covered.lower() != target.lower():
            s["category"] = covered
            s["target_category"] = ""
            s["is_new_category"] = False

    # Per-suggestion placement check for add_skill — does the proposed category
    # accept this skill's domain? If not, try to find a better existing category.
    validated: list = []
    for s in cleaned:
        if s.get("mode") != "add_skill":
            validated.append(s)
            continue
        skill = (s.get("skill") or "").strip()
        category = (s.get("category") or "").strip()
        target_category = (s.get("target_category") or "").strip()
        target = category or target_category
        verdict = _tax.category_accepts(target, skill)
        if verdict is False:
            best = _tax.best_existing_category(skill, categories)
            if best:
                s["category"] = best
                s["target_category"] = ""
                s["is_new_category"] = False
                validated.append(s)
            continue
        validated.append(s)

    if not validated and suggestions:
        logger.warning("[tailor_skills] all %d suggestion(s) dropped by validation", len(suggestions))

    # LLM post-filter: contextual gate on add_skill items only.
    # Structural ops (remove/rename/move/delete) operate on existing skills and are safe.
    add_skill_suggs = [s for s in validated if s.get("mode") == "add_skill"]
    structural_suggs = [s for s in validated if s.get("mode") != "add_skill"]
    if add_skill_suggs:
        add_skill_suggs = await _llm_filter_skill_suggestions(
            add_skill_suggs, jd_text, experience_ctx, projects_ctx
        )
    return structural_suggs + add_skill_suggs


async def llm_clean_tech_field(tech_str: str) -> str:
    """Remove noise from a project's comma-separated tech string.

    Keeps only genuine named technologies (languages, frameworks, libraries,
    databases, platforms, tools, cloud services). Removes generic English words,
    JD buzzwords, soft-skill terms, and role descriptors.

    Fast model + cache — each unique tech string is LLM-processed at most once.
    Falls back to original on any error.
    """
    if not (tech_str or "").strip():
        return tech_str
    items = [t.strip() for t in tech_str.split(",") if t.strip()]
    if not items:
        return tech_str

    prompt = (
        "Filter this list of items from a software project's tech stack. "
        "Return ONLY genuine, specific technology names — programming languages, "
        "frameworks, libraries, databases, platforms, tools, or cloud services.\n\n"
        "EXCLUDE anything that is NOT a specific named technology: "
        "generic English words (field, idea, language, minimum, money, form, history, "
        "intelligence, leadership, identity, mobile, list, science, re, law, set), "
        "soft skills, business nouns, adjectives, and any word a developer would "
        "not include in a 'Tech Stack' section of a project README.\n\n"
        f"Items: {json.dumps(items)}\n\n"
        'Return JSON: {"tech": ["item1", "item2", ...]}'
    )
    try:
        raw = await _chat(
            [{"role": "user", "content": prompt}],
            json_mode=True,
            model=get_model_name(),
            use_cache=True,
        )
        result = json.loads(raw)
        filtered = result.get("tech", items)
        valid_lower = {i.lower(): i for i in items}
        kept = [valid_lower[t.lower()] for t in filtered if t.lower() in valid_lower]
        if not kept:
            return tech_str
        return ", ".join(kept)
    except Exception as e:
        logger.warning("[llm_clean_tech_field] failed (%s) — using original", e)
        return tech_str


# Cache for hard requirement extraction
_HARD_REQ_CACHE: dict = {}

_SKILL_JUNK_TOKENS = {
    "proficiency", "knowledge", "experience", "understanding", "ability",
    "practices", "principles", "fundamentals", "robust", "scalable",
    "modern", "strong", "best", "skills", "skill",
}
_SKILL_JUNK_PREFIXES = (
    "creating ", "building ", "developing ", "working ", "writing ",
    "designing ", "implementing ", "knowledge of ", "experience with ",
    "experience in ", "proficiency in ", "understanding of ", "ability to ",
)


def _is_atomic_skill(s: str) -> bool:
    """Reject descriptive phrases; keep atomic tool/language names."""
    s_clean = (s or "").strip()
    if not s_clean:
        return False
    if len(s_clean.split()) > 3:
        return False
    lower = s_clean.lower()
    if any(lower.startswith(p) for p in _SKILL_JUNK_PREFIXES):
        return False
    tokens = set(re.findall(r"[a-z]+", lower))
    if tokens & _SKILL_JUNK_TOKENS:
        return False
    return True


# Strip bullet/list markers and label prefixes from a diagnosis paragraph.
# Defensive post-filter in case the LLM ignores the "no lists" rule.
_DIAG_LIST_LINE_RE = re.compile(r'^\s*(?:[-•*–—]+|\d+[.)])\s+', re.MULTILINE)


def _clean_diagnosis(text: str) -> str:
    if not text:
        return ""
    cleaned = _DIAG_LIST_LINE_RE.sub('', text).strip()
    # Collapse double spaces/newlines created by removed markers
    cleaned = re.sub(r'\n{2,}', ' ', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    return cleaned


_DIAG_CITE_RE = re.compile(r"'([^']{2,40})'")


def _verify_diagnosis(
    explanation: str,
    section_text: str,
    missing_keywords: list,
) -> str:
    """Drop sentences that cite a term already present in the section text.
    A cited term is legitimate only when it appears in the deterministic
    missing_keywords list. This catches LLM hallucinations where the model
    claims the resume lacks a term it actually contains."""
    if not explanation:
        return ""
    hay = (section_text or "").lower()
    allowed = {k.lower() for k in (missing_keywords or [])}
    kept: list = []
    tech_chars = r'[a-zA-Z0-9+#.\-]'
    for sent in re.split(r"(?<=[.!?])\s+", explanation):
        suspicious = False
        for term in _DIAG_CITE_RE.findall(sent):
            tl = term.lower().strip()
            if not tl or tl in allowed:
                continue
            # Match word boundary with tech-friendly characters to prevent substring collisions
            pattern = f'(?<!{tech_chars})' + re.escape(tl) + f'(?!{tech_chars})'
            if re.search(pattern, hay) is not None:
                suspicious = True
                break
        if not suspicious:
            kept.append(sent)
    return " ".join(kept).strip()


async def analyze_low_sections(
    jd_text: str,
    low_sections: list,
    section_gaps: dict | None = None,
) -> dict:
    """Diagnose each low-scoring resume section in plain English.

    Args:
        jd_text: Job description text.
        low_sections: list of {"section": str, "score": int, "text": str}
            (text is the rendered plaintext of that resume section).
        section_gaps: optional dict mapping section name → list of JD terms
            that are demonstrably absent from THAT section. Passed to the
            LLM as ground truth and used to validate the response.

    Returns:
        {section_name: explanation_text}. Empty dict on any failure — caller
        should fall back to the existing `reason` string.
    """
    if not low_sections:
        return {}

    valid_sections = {s.get("section") for s in low_sections if s.get("section")}
    if not valid_sections:
        return {}

    # Map lowercase section name -> original section name to support case-insensitive checks
    section_map = {s.lower(): s for s in valid_sections}

    # Cap inputs: max 4 sections, JD 2000, section text 1500. Attach the
    # deterministic per-section missing keywords so the LLM can only cite
    # from a vetted list — not invent gaps from world knowledge.
    capped = [
        {
            "section": s["section"],
            "score": int(s.get("score", 0)),
            "text": (s.get("text") or "")[:1500],
            "missing_keywords": (section_gaps or {}).get(s["section"], [])[:10],
        }
        for s in low_sections[:4]
        if s.get("section")
    ]

    user_content = (
        "<JD>\n"
        f"{jd_text[:2000]}\n"
        "</JD>\n\n"
        "<LOW_SECTIONS>\n"
        f"{json.dumps(capped, ensure_ascii=False)}\n"
        "</LOW_SECTIONS>\n\n"
        "Diagnose each section above."
    )

    try:
        content = await _chat(
            [{"role": "system", "content": PROMPT_SECTION_DIAGNOSIS_SYSTEM},
             {"role": "user", "content": user_content}],
            json_mode=True,
        )
        parsed = json.loads(content)
    except Exception as e:
        logger.warning(f"[analyze_low_sections] json_mode failed, retrying: {e}")
        try:
            content = await _chat(
                [{"role": "system", "content": PROMPT_SECTION_DIAGNOSIS_SYSTEM + "\nRespond ONLY with valid JSON."},
                 {"role": "user", "content": user_content}],
                json_mode=False,
            )
            start = content.find("{"); end = content.rfind("}") + 1
            if start == -1 or end <= 0:
                return {}
            parsed = json.loads(content[start:end])
        except Exception as e2:
            logger.warning(f"[analyze_low_sections] retry failed: {e2}")
            return {}

    explanations = parsed.get("explanations") if isinstance(parsed, dict) else None
    if not isinstance(explanations, list):
        return {}

    out: dict[str, str] = {}
    for entry in explanations:
        if not isinstance(entry, dict):
            continue
        section = entry.get("section")
        why = entry.get("why")
        if not isinstance(section, str) or not isinstance(why, str):
            continue
        sect_lower = section.lower()
        if sect_lower not in section_map:
            continue
        orig_section = section_map[sect_lower]
        if orig_section in out:
            continue
        cleaned = _clean_diagnosis(why)
        section_text = next((s["text"] for s in capped if s["section"] == orig_section), "")
        miss = (section_gaps or {}).get(orig_section, [])
        cleaned = _verify_diagnosis(cleaned, section_text, miss)
        if cleaned:
            out[orig_section] = cleaned
    return out


_BLOCKER_KINDS = {"experience", "seniority", "education"}


async def explain_match_blockers(jd_text: str, ceiling: dict | None) -> list:
    """Plain-English coaching for hard-requirement gaps (years / seniority /
    degree) that cap the match score and cannot be fixed by keyword tailoring.

    Args:
        jd_text: Job description text.
        ceiling: detect_ceiling() output — {score, reasons, exp_required,
            exp_actual}. The deterministic ground truth; the LLM may only
            explain constraints listed here.

    Returns:
        list of {"kind", "headline", "detail"}. Empty list (NO LLM call) when
        the ceiling has no blocking reasons.
    """
    reasons = (ceiling or {}).get("reasons") or []
    if not reasons:
        return []

    payload = {
        "reasons": reasons,
        "exp_required": (ceiling or {}).get("exp_required"),
        "exp_actual": (ceiling or {}).get("exp_actual"),
    }
    user_content = (
        "<JD>\n"
        f"{jd_text[:2000]}\n"
        "</JD>\n\n"
        "<CEILING>\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
        "</CEILING>\n\n"
        "Explain each blocker above and how to mitigate it."
    )

    try:
        content = await _chat(
            [{"role": "system", "content": PROMPT_MATCH_BLOCKERS_SYSTEM},
             {"role": "user", "content": user_content}],
            json_mode=True,
        )
        parsed = json.loads(content)
    except Exception as e:
        logger.warning(f"[explain_match_blockers] json_mode failed, retrying: {e}")
        try:
            content = await _chat(
                [{"role": "system", "content": PROMPT_MATCH_BLOCKERS_SYSTEM + "\nRespond ONLY with valid JSON."},
                 {"role": "user", "content": user_content}],
                json_mode=False,
            )
            start = content.find("{"); end = content.rfind("}") + 1
            if start == -1 or end <= 0:
                return []
            parsed = json.loads(content[start:end])
        except Exception as e2:
            logger.warning(f"[explain_match_blockers] retry failed: {e2}")
            return []

    blockers = parsed.get("blockers") if isinstance(parsed, dict) else None
    if not isinstance(blockers, list):
        return []

    out: list = []
    seen: set = set()
    for entry in blockers:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        headline = entry.get("headline")
        detail = entry.get("detail")
        if kind not in _BLOCKER_KINDS or kind in seen:
            continue
        if not isinstance(headline, str) or not isinstance(detail, str):
            continue
        cleaned = _clean_diagnosis(detail)
        if not cleaned:
            continue
        seen.add(kind)
        out.append({"kind": kind, "headline": headline.strip(), "detail": cleaned})
    return out


_SKILLS_MAX_CATEGORIES = 10
_SKILLS_MAX_TOTAL = 40


def _format_evidence_block(label: str, items: list[str], cap: int = 4000) -> str:
    """Render a delimited evidence block for the goldmine prompt.
    Truncates aggressively so the prompt stays under model limits."""
    if not items:
        return f"<{label}>\n(none provided)\n</{label}>"
    joined = "\n".join(items)
    if len(joined) > cap:
        joined = joined[:cap].rsplit("\n", 1)[0] + "\n..."
    return f"<{label}>\n{joined}\n</{label}>"


def _normalize_skills_payload(parsed: dict) -> list[dict]:
    """Coerce the LLM response into [{category: str, skills: [str]}].
    Drops empty categories, dedups within & across categories, caps totals."""
    raw = parsed.get("skills") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return []
    seen_skills_canon: set[str] = set()
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        category = (entry.get("category") or "").strip()
        skills_raw = entry.get("skills")
        if not category or not isinstance(skills_raw, list):
            continue
        clean_skills: list[str] = []
        for s in skills_raw:
            if not isinstance(s, str):
                continue
            name = s.strip()
            if not name:
                continue
            canon = name.lower()
            if canon in seen_skills_canon:
                continue
            seen_skills_canon.add(canon)
            clean_skills.append(name)
            if len(seen_skills_canon) >= _SKILLS_MAX_TOTAL:
                break
        if clean_skills:
            out.append({"category": category, "skills": clean_skills})
        if len(out) >= _SKILLS_MAX_CATEGORIES:
            break
        if len(seen_skills_canon) >= _SKILLS_MAX_TOTAL:
            break
    return out


async def generate_skills_from_tailored(
    jd_text: str,
    tailored_summary: Optional[str],
    tailored_experience: list[dict],
    tailored_projects: list[dict],
    tailored_education: list[dict],
    intensity: str = "balanced",
) -> dict:
    """Wholesale Skills section regen driven by JD + tailored evidence.

    Returns {"skills": [{category, skills: [str]}, ...], "reasoning": str}.
    Empty skills list on any failure — caller decides UX fallback.
    """
    exp_lines: list[str] = []
    for e in tailored_experience or []:
        head = f"{(e.get('title') or '').strip()} @ {(e.get('company') or '').strip()}".strip(" @")
        if head:
            exp_lines.append(head)
        for b in (e.get("bullets") or []):
            if b:
                exp_lines.append(f"- {b}")

    proj_lines: list[str] = []
    for p in tailored_projects or []:
        name = (p.get("name") or "").strip()
        tech = (p.get("tech") or "").strip()
        head = name + (f" ({tech})" if tech else "")
        if head:
            proj_lines.append(head)
        for b in (p.get("bullets") or []):
            if b:
                proj_lines.append(f"- {b}")

    edu_lines: list[str] = []
    for ed in tailored_education or []:
        head_parts = [(ed.get("degree") or "").strip()]
        if ed.get("field"):
            head_parts.append(f"in {ed['field']}")
        head_parts.append("@")
        head_parts.append((ed.get("institution") or "").strip())
        head = " ".join(p for p in head_parts if p).strip(" @")
        if head:
            edu_lines.append(head)
        for d in (ed.get("details") or []):
            if d:
                edu_lines.append(f"- {d}")

    summary_block = (tailored_summary or "").strip() or "(none provided)"

    user_content = (
        f"<JD>\n{jd_text[:4000]}\n</JD>\n\n"
        f"<SUMMARY>\n{summary_block[:1500]}\n</SUMMARY>\n\n"
        + _format_evidence_block("EXPERIENCE", exp_lines)
        + "\n\n"
        + _format_evidence_block("PROJECTS", proj_lines)
        + "\n\n"
        + _format_evidence_block("COURSEWORK", edu_lines, cap=2000)
        + "\n\nProduce the Skills section now."
    )

    parsed: dict = {}
    try:
        content = await _chat(
            [{"role": "system", "content": PROMPT_GENERATE_SKILLS_GOLDMINE_SYSTEM + INTENSITY_INSTRUCTIONS[intensity]},
             {"role": "user", "content": user_content}],
            json_mode=True,
            model=get_smart_model(),
        )
        parsed = json.loads(content)
    except Exception as e:
        logger.warning(f"[generate_skills_from_tailored] json_mode failed, retrying: {e}")
        try:
            content = await _chat(
                [{"role": "system", "content": PROMPT_GENERATE_SKILLS_GOLDMINE_SYSTEM + INTENSITY_INSTRUCTIONS[intensity] + "\nRespond ONLY with valid JSON."},
                 {"role": "user", "content": user_content}],
                json_mode=False,
                model=get_smart_model(),
            )
            start = content.find("{"); end = content.rfind("}") + 1
            if start == -1 or end <= 0:
                return {"skills": [], "reasoning": ""}
            parsed = json.loads(content[start:end])
        except Exception as e2:
            logger.warning(f"[generate_skills_from_tailored] retry failed: {e2}")
            return {"skills": [], "reasoning": ""}

    skills = _normalize_skills_payload(parsed)
    reasoning = parsed.get("reasoning") if isinstance(parsed, dict) else ""
    if not isinstance(reasoning, str):
        reasoning = ""
    return {"skills": skills, "reasoning": reasoning.strip()}


async def extract_jd_hard_requirements(jd_text: str) -> dict:
    """Parse JD for structural ceiling inputs."""
    if not jd_text or not jd_text.strip():
        return {
            "min_years_experience": None,
            "required_degrees": [],
            "seniority_level": None,
            "required_skills_hard": [],
        }

    key = hash(jd_text)
    if key in _HARD_REQ_CACHE:
        return _HARD_REQ_CACHE[key]

    system = PROMPT_EXTRACT_JD_HARD_REQUIREMENTS

    try:
        content = await _chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"JD:\n{jd_text[:6000]}"}],
            json_mode=True,
        )
        parsed = json.loads(content)
        raw_skills = [s for s in (parsed.get("required_skills_hard") or []) if isinstance(s, str) and s.strip()]
        out = {
            "min_years_experience": parsed.get("min_years_experience") if isinstance(parsed.get("min_years_experience"), int) else None,
            "required_degrees": [d.lower() for d in (parsed.get("required_degrees") or []) if isinstance(d, str)],
            "seniority_level": (parsed.get("seniority_level") or "").lower() or None if isinstance(parsed.get("seniority_level"), str) else None,
            "required_skills_hard": [s for s in raw_skills if _is_atomic_skill(s)],
        }
        _HARD_REQ_CACHE[key] = out
        return out
    except Exception as e:
        logger.warning(f"[extract_jd_hard_requirements] failed: {e}")
        return {
            "min_years_experience": None,
            "required_degrees": [],
            "seniority_level": None,
            "required_skills_hard": [],
        }

async def analyze_overall_match(jd_text: str, resume_text: str, score: int) -> dict:
    """Generate overall diagnosis and actionable suggestions for the entire match.
    
    Args:
        jd_text: Job description text.
        resume_text: Plaintext resume.
        score: The overall match score.
        
    Returns:
        {"diagnosis": {"headline": str, "detail": str, "theme": str}, "suggestions": [str]}
    """
    system_prompt = (
        "You are an expert ATS and technical recruiter. Given a job description, a candidate's resume, and their current match score, "
        "provide a concise diagnosis of the match and a list of 2-3 specific, highly actionable suggestions to improve the resume.\n\n"
        "Return a JSON object strictly following this structure:\n"
        "{\n"
        '  "diagnosis": {\n'
        '    "headline": "Short punchy title (e.g., Strong Match, Missing Core Tech)",\n'
        '    "detail": "1-2 sentence explanation of why the score is what it is.",\n'
        '    "theme": "One of: success, warning, danger, info (use success for >=80, warning for 50-79, danger for <50)"\n'
        "  },\n"
        '  "suggestions": [\n'
        '    "Actionable step 1",\n'
        '    "Actionable step 2"\n'
        "  ]\n"
        "}\n\n"
        "Keep suggestions brief, specific to the JD gaps, and highly actionable."
    )
    user_content = (
        f"<MATCH_SCORE>{score}</MATCH_SCORE>\n\n"
        f"<JD>\n{jd_text[:3000]}\n</JD>\n\n"
        f"<RESUME>\n{resume_text[:3000]}\n</RESUME>"
    )
    
    try:
        content = await _chat(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_content}],
            json_mode=True,
        )
        parsed = json.loads(content)
        return {
            "diagnosis": parsed.get("diagnosis", {
                "headline": "Analysis Complete",
                "detail": "Match analysis finished.",
                "theme": "info"
            }),
            "suggestions": parsed.get("suggestions", [])[:3]
        }
    except Exception as e:
        logger.warning(f"analyze_overall_match failed: {e}")
        return {
            "diagnosis": {
                "headline": "Match Complete",
                "detail": f"Resume evaluated with a score of {score}.",
                "theme": "info"
            },
            "suggestions": ["Consider adding more keywords from the job description."]
        }
