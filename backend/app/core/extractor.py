"""
Parse a resume's raw text into the structured Resume schema with one LLM call.

Designed for resilience: if the LLM returns malformed JSON, we attempt a
loose extract and fall back to a minimal Resume so the rest of the pipeline
still works.
"""
import json
import logging
import re
from app.core.llm_client import _chat
from app.core.llm_prompts import PROMPT_EXTRACT_RESUME_SYSTEM
from app.models.resume_schema import Resume

logger = logging.getLogger(__name__)


_HEADER_INDICATORS = (
    "experience", "education", "projects", "skills", "certifications",
    "work history", "employment", "achievements", "expertise",
)


def _looks_like_hallucinated_summary(s: str | None) -> bool:
    """A real Summary is a short paragraph. If `s` is suspiciously long,
    contains bullet glyphs, or echoes a section header inside itself, the
    LLM almost certainly stuffed unrelated content into the summary field."""
    if not s:
        return False
    if len(s) > 600:
        return True
    if "\n•" in s or "\n- " in s or "\n– " in s or "\n* " in s:
        return True
    lower = s.lower()
    # A genuine summary can mention "experience" inline; require two distinct
    # section-header words to flag as paste-in.
    hits = sum(1 for h in _HEADER_INDICATORS if h in lower)
    if hits >= 2 and len(s) > 250:
        return True
    return False


def _loose_json_extract(text: str) -> dict:
    """Best-effort: find the first {...} block and parse it."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    chunk = text[start : end + 1]
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        # Strip trailing commas — a common LLM mistake
        cleaned = re.sub(r",(\s*[}\]])", r"\1", chunk)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


_HEADING_PATTERNS = [
    (re.compile(r"^\s*(?:professional\s+)?summary\b", re.I | re.M), "summary"),
    (re.compile(r"^\s*(?:profile|objective|about\s+me)\b", re.I | re.M), "summary"),
    (re.compile(r"^\s*(?:work\s+|professional\s+)?experience\b", re.I | re.M), "experience"),
    (re.compile(r"^\s*employment\s+history\b", re.I | re.M), "experience"),
    (re.compile(r"^\s*education\b", re.I | re.M), "education"),
    (re.compile(r"^\s*academic\s+background\b", re.I | re.M), "education"),
    (re.compile(r"^\s*academic\s+history\b", re.I | re.M), "education"),
    (re.compile(r"^\s*(?:technical\s+|personal\s+)?projects\b", re.I | re.M), "projects"),
    (re.compile(r"^\s*(?:technical\s+)?skills\b", re.I | re.M), "skills"),
    (re.compile(r"^\s*expertise\b", re.I | re.M), "skills"),
    (re.compile(r"^\s*core\s+competencies\b", re.I | re.M), "skills"),
    (re.compile(r"^\s*certifications?\b", re.I | re.M), "certifications"),
    (re.compile(r"^\s*certificates?\b", re.I | re.M), "certifications"),
    (re.compile(r"^\s*(?:selected\s+)?publications\b", re.I | re.M), "publications"),
    (re.compile(r"^\s*(?:honors?\s*(?:and|&)?\s*)?awards\b", re.I | re.M), "awards"),
    (re.compile(r"^\s*achievements\b", re.I | re.M), "awards"),
    (re.compile(r"^\s*(?:language\s+proficiency|languages)\b", re.I | re.M), "languages"),
    (re.compile(r"^\s*volunteer(?:\s+experience)?\b", re.I | re.M), "volunteer"),
    (re.compile(r"^\s*community\s+service\b", re.I | re.M), "volunteer"),
    (re.compile(r"^\s*patents?\b", re.I | re.M), "patents"),
    (re.compile(r"^\s*(?:talks|presentations)\b", re.I | re.M), "talks"),
]


def _scan_order_from_text(raw_text: str, extra_titles: list[str] = None) -> list[str]:
    """Scan raw_text for section headings; return canonical keys in position
    order. Used to enforce strict fidelity to the original document's layout.
    """
    hits = []
    seen = set()

    # 1. Look for standard headings via regex
    for pat, key in _HEADING_PATTERNS:
        m = pat.search(raw_text)
        if m and key not in seen:
            hits.append((m.start(), key))
            seen.add(key)

    # 2. Look for extra section titles provided by LLM
    if extra_titles:
        for title in extra_titles:
            # Case-insensitive search for the exact title on its own line
            # or with some minor padding.
            pat = re.compile(rf"^\s*{re.escape(title)}\s*$", re.I | re.M)
            m = pat.search(raw_text)
            if m:
                key = f"extra:{title}"
                if key not in seen:
                    hits.append((m.start(), key))
                    seen.add(key)

    hits.sort(key=lambda x: x[0])
    return [k for _, k in hits]


_SECTION_MAP = {
    "summary": "summary",
    "profile": "summary",
    "objective": "summary",
    "professional summary": "summary",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "work history": "experience",
    "employment history": "experience",
    "education": "education",
    "academic background": "education",
    "projects": "projects",
    "personal projects": "projects",
    "technical projects": "projects",
    "skills": "skills",
    "technical skills": "skills",
    "expertise": "skills",
    "core competencies": "skills",
    "proficiencies": "skills",
    "certifications": "certifications",
    "certificates": "certifications",
    "publications": "publications",
    "selected publications": "publications",
    "awards": "awards",
    "honors": "awards",
    "honors and awards": "awards",
    "achievements": "awards",
    "accomplishments": "awards",
    "languages": "languages",
    "language proficiency": "languages",
    "volunteer": "volunteer",
    "volunteer experience": "volunteer",
    "volunteering": "volunteer",
    "community service": "volunteer",
    "patents": "patents",
    "inventions": "patents",
    "talks": "talks",
    "presentations": "talks",
    "talks and presentations": "talks",
    "speaking engagements": "talks",
}


def _normalize_order(raw_order: list | None, extra_titles: list[str]) -> list[str]:
    """Map raw LLM section titles to canonical section keys.

    Known sections → their lowercase key ("Experience" → "experience").
    Titles matching an extra_sections title → "extra:<Title>".
    Anything unrecognized → dropped (prevents stale/hallucinated entries).
    """
    if not raw_order:
        return []
    result = []
    seen_keys = set()
    for s in raw_order:
        if not s:
            continue
        key = s.lower().strip()
        if key in _SECTION_MAP:
            canonical = _SECTION_MAP[key]
            if canonical not in seen_keys:
                result.append(canonical)
                seen_keys.add(canonical)
        elif s in extra_titles:
            if f"extra:{s}" not in seen_keys:
                result.append(f"extra:{s}")
                seen_keys.add(f"extra:{s}")
    return result


def _normalize_for_substring(s: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation tails for matching."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    # Strip trailing dots/colons that LLM often adds
    s = s.rstrip(".,;: ")
    return s


def _appears_in(needle: str, haystack: str) -> bool:
    """Case-insensitive substring check with whitespace normalization."""
    n = _normalize_for_substring(needle)
    if not n or len(n) < 3:
        return False
    return n in haystack


def _dedupe_education_field(resume: Resume) -> None:
    """If education.field is already substring of education.degree, drop it.
    Handles the dash variant "Bachelor of Technology - Information Technology"
    where the LLM keeps the field merged into the degree string AND also sets
    field independently, which would otherwise render as "<degree> in <field>"
    with the field portion duplicated."""
    for ed in resume.education:
        if not ed.field or not ed.degree:
            continue
        d = ed.degree.lower()
        f = ed.field.lower().strip()
        if f and f in d:
            ed.field = None


def _clean_coursework(resume: Resume) -> None:
    """Consolidate Coursework from extra_sections and deduplicate within education."""
    cw_titles = {"coursework", "relevant coursework", "key coursework", "related coursework"}
    
    # 1. Move extra_sections coursework into the first education entry
    extra_courseworks = [ex for ex in resume.extra_sections if ex.title.lower().strip() in cw_titles]
    if extra_courseworks and resume.education:
        courses = []
        for ex in extra_courseworks:
            for item in ex.items:
                if item.header: courses.append(item.header)
                if item.text: courses.append(item.text)
                courses.extend(item.bullets)
        if courses:
            resume.education[0].details.append("Relevant Coursework: " + ", ".join(courses))
            
    # Remove from extra_sections
    resume.extra_sections = [ex for ex in resume.extra_sections if ex.title.lower().strip() not in cw_titles]
    
    # 2. Deduplicate coursework lines within each education entry
    for ed in resume.education:
        courses = []
        other_lines = []
        for d in ed.details:
            d_lower = d.lower().strip()
            if d_lower.startswith("relevant coursework:") or d_lower.startswith("coursework:"):
                parts = d.split(":", 1)
                if len(parts) > 1:
                    for c in parts[1].split(","):
                        c = c.strip()
                        # simple case-insensitive deduplication while preserving original case
                        if c and not any(c.lower() == existing.lower() for existing in courses):
                            courses.append(c)
            else:
                other_lines.append(d)
                
        if courses:
            other_lines.append("Relevant Coursework: " + ", ".join(courses))
        ed.details = other_lines


def _dedupe_canonical_extra_sections(resume: Resume) -> None:
    """Drop extra_sections whose title maps to a standard section that already
    has content. The LLM sometimes emits e.g. "TECHNICAL SKILLS" as BOTH the
    canonical field (skills) AND a redundant extra_section, which then renders
    twice (once inline, once as broken entries with null subheaders)."""
    kept = []
    for ex in resume.extra_sections:
        canonical = _SECTION_MAP.get(ex.title.lower().strip())
        if canonical:
            val = getattr(resume, canonical, None)
            has_content = bool(val.strip()) if isinstance(val, str) else bool(val)
            if has_content:
                continue  # canonical field already holds this — drop the dupe
        kept.append(ex)
    resume.extra_sections = kept


def _filter_hallucinated_sections(resume: Resume, raw_text: str) -> None:
    """Mutate resume in place — drop entries whose identifying field doesn't
    appear in the raw source text. Catches LLM fabrications from world knowledge
    (e.g., known author's publication metadata) that slip past the prompt rules."""
    hay = _normalize_for_substring(raw_text)
    if not hay:
        return

    resume.publications = [p for p in resume.publications if _appears_in(p.title, hay)]
    resume.awards = [a for a in resume.awards if _appears_in(a.title, hay)]
    resume.patents = [p for p in resume.patents if _appears_in(p.title, hay)]
    resume.talks = [t for t in resume.talks if _appears_in(t.title, hay)]
    resume.languages = [l for l in resume.languages if _appears_in(l.name, hay)]
    resume.volunteer = [
        v for v in resume.volunteer
        if _appears_in(v.role, hay) or _appears_in(v.organization, hay)
    ]

    # Education: validate location and institution against raw text. The LLM
    # has been observed to autocorrect spelling (e.g., "Manipal" -> "Manipur"),
    # which silently injects wrong cities into rendered output.
    for ed in resume.education:
        if ed.location and not _appears_in(ed.location, hay):
            city = ed.location.split(",")[0].strip()
            if city and not _appears_in(city, hay):
                ed.location = None
        if ed.institution and not _appears_in(ed.institution, hay):
            logger.warning(
                "Education institution '%s' not found in raw text - possible LLM hallucination",
                ed.institution,
            )

    # Phone: must have at least 7 digits matching source
    if resume.contact.phone:
        phone_digits = re.sub(r"\D", "", resume.contact.phone)
        if len(phone_digits) >= 7:
            text_digits = re.sub(r"\D", "", raw_text)
            if phone_digits not in text_digits:
                resume.contact.phone = None
        elif phone_digits:
            # Has digits but very few — keep if appears as-is (e.g., placeholders)
            if resume.contact.phone.lower() not in hay:
                resume.contact.phone = None


async def extract_resume(raw_text: str) -> Resume:
    user_prompt = f"Resume text:\n\n{raw_text[:8000]}"
    try:
        content = await _chat(
            [
                {"role": "system", "content": PROMPT_EXTRACT_RESUME_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=True,
        )
        data = json.loads(content)
    except Exception as e:
        logger.warning(f"JSON mode failed, falling back: {e}")
        try:
            content = await _chat(
                [
                    {"role": "system", "content": PROMPT_EXTRACT_RESUME_SYSTEM + "\nReturn ONLY the JSON object, no other text."},
                    {"role": "user", "content": user_prompt},
                ],
                json_mode=False,
            )
            data = _loose_json_extract(content)
        except Exception as inner:
            logger.exception(f"Fallback also failed: {inner}")
            data = {}

    if isinstance(data, dict) and _looks_like_hallucinated_summary(data.get("summary")):
        logger.info("Dropping suspect summary (looks fabricated or pasted-in)")
        data["summary"] = None

    try:
        resume = Resume.model_validate(data)
    except Exception as e:
        logger.exception(f"Schema validation failed, returning minimal Resume: {e}")
        # Never dump raw text into summary — that creates a fake Summary
        # section in every downstream render. Leave it null; the user can
        # re-upload if the parse was really that broken.
        name = (data.get("name") if isinstance(data, dict) else None) or "Unknown"
        return Resume(name=name)

    # Hard fidelity guard: drop entries whose identifying field doesn't appear
    # in source text. Catches LLM fabrications from world knowledge that slip
    # past the prompt rules.
    _filter_hallucinated_sections(resume, raw_text)
    _dedupe_education_field(resume)
    _clean_coursework(resume)
    _dedupe_canonical_extra_sections(resume)

    if isinstance(data, dict):
        extra_titles = [e.title for e in resume.extra_sections]
        
        # 1. Normalize what the LLM found (this identifies WHICH sections exist)
        found_sections = _normalize_order(data.get("section_order", []), extra_titles)
        
        # 2. Add any standard sections that have content but weren't in section_order
        for key in [
            "summary", "experience", "education", "projects", "skills",
            "certifications", "publications", "awards", "languages",
            "volunteer", "patents", "talks",
        ]:
            val = getattr(resume, key, None)
            # Use explicit check for non-empty lists/strings
            has_content = False
            if isinstance(val, list):
                has_content = len(val) > 0
            elif isinstance(val, str):
                has_content = len(val.strip()) > 0
            elif val is not None:
                has_content = True

            if has_content and key not in found_sections:
                found_sections.append(key)
        for extra in resume.extra_sections:
            key = f"extra:{extra.title}"
            if key not in found_sections:
                found_sections.append(key)

        # 3. Dynamic Ordering Fix: Always re-scan text to find the TRUE physical order.
        # This overrides the LLM's "canonical" order (e.g. Education first) with the 
        # actual layout of the user's document.
        physical_order = _scan_order_from_text(raw_text, extra_titles)
        
        # Merge: use physical_order as the sequence, but only include sections 
        # that actually have content (found_sections).
        final_order = []
        seen = set()
        for s in physical_order:
            if s in found_sections and s not in seen:
                final_order.append(s)
                seen.add(s)
        
        # Append any sections found by LLM that regex missed (edge cases)
        for s in found_sections:
            if s not in seen:
                final_order.append(s)
                seen.add(s)

        resume.section_order = final_order

    return resume
