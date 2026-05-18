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
from app.models.resume_schema import Resume

logger = logging.getLogger(__name__)


_EXTRACTION_SYSTEM = """You are a precise resume parser. Given a resume's raw text, extract its content into a JSON object that matches the schema below EXACTLY.

ABSOLUTE FIDELITY RULES (these override every other instruction):
- If the resume has NO Summary / Profile / Objective / About section, you MUST set "summary" to null. Do NOT generate one from the candidate's experience, education, or skills.
- A heading like "Summary", "Profile", "About Me", or "Objective" must be literally present in the source for a non-null "summary" to be returned.
- If the resume has no Projects section, "projects" MUST be [].
- If the resume has no Certifications section, "certifications" MUST be [].
- If the resume has no Publications section, "publications" MUST be [].
- If the resume has no Awards/Honors section, "awards" MUST be [].
- If the resume has no Languages section, "languages" MUST be [].
- If the resume has no Volunteer Experience section, "volunteer" MUST be [].
- If the resume has no Patents section, "patents" MUST be [].
- If the resume has no Talks/Presentations section, "talks" MUST be [].
- If the resume has no extra/non-standard sections (anything besides those listed above), "extra_sections" MUST be [].
- Never invent dates, companies, titles, bullets, or skills that are not literally present in the source text.

Rules:
- Use the candidate's exact wording — do not paraphrase, do not add information that isn't there.
- If a field is missing from the resume, use null (for strings) or an empty array (for lists).
- For dates, preserve original formatting (e.g., "Aug 2020", "Jun 2025 – Dec 2025", "Present", "May 2024 - Current").
- Each bullet point becomes its own string. Strip leading bullet characters (•, -, –, *).
- For skills: if the resume groups skills under category labels (e.g., "Backend:", "Programming:"), use those category names. Otherwise put everything under category "Skills". DO NOT lump spoken languages here — those go in "languages".
- For publications: parse each entry into {title, authors, venue, year, doi, url}. If you can't split it, put the whole citation in "title" and leave others null.
- For awards: parse each into {title, issuer, date, description}. Honors and accolades go here, NOT in certifications.
- For languages: parse each into {name, proficiency}. Proficiency is one of: Native, Fluent, Conversational, Basic. If unknown, leave null.
- For volunteer: parse each into {role, organization, location, start_date, end_date, bullets}. Same shape as experience.
- For patents: parse each into {title, number, date, status, authors}. Status is "Granted" or "Pending".
- For talks: parse each into {title, venue, date, type}. Type is "Conference", "Workshop", or "Seminar".
- section_order: list ALL section headings top-to-bottom using lowercase canonical keys: summary, experience, projects, education, skills, certifications, publications, awards, languages, volunteer, patents, talks. Prefix only truly unrecognized sections with "extra:" (e.g. "extra:Hobbies"). Include every section present.
- extra_sections: ONLY for sections that don't match any of the standard types above. Do NOT put awards/languages/volunteer/patents/talks here — they have first-class fields. Set content_type to "entries" if items have headers or bullets, "list" if short one-liners, "text" if a prose block.
- Return ONLY the JSON. No prose, no markdown fence, no commentary.

SCHEMA:
{
  "name": "string",
  "contact": {
    "email": "string|null",
    "phone": "string|null",
    "location": "string|null",
    "linkedin": "string|null",
    "github": "string|null",
    "website": "string|null"
  },
  "summary": "string|null",
  "experience": [
    {
      "title": "string",
      "company": "string",
      "location": "string|null",
      "start_date": "string|null",
      "end_date": "string|null",
      "bullets": ["string"]
    }
  ],
  "education": [
    {
      "institution": "string",
      "degree": "string|null",
      "field": "string|null",
      "location": "string|null",
      "start_date": "string|null",
      "end_date": "string|null",
      "gpa": "string|null",
      "details": ["string"]
    }
  ],
  "projects": [
    {
      "name": "string",
      "tech": "string|null",
      "bullets": ["string"]
    }
  ],
  "skills": [
    {
      "category": "string",
      "skills": ["string"]
    }
  ],
  "certifications": ["string"],
  "publications": [
    {
      "title": "string",
      "authors": "string|null",
      "venue": "string|null",
      "year": "string|null",
      "doi": "string|null",
      "url": "string|null"
    }
  ],
  "awards": [
    {
      "title": "string",
      "issuer": "string|null",
      "date": "string|null",
      "description": "string|null"
    }
  ],
  "languages": [
    {
      "name": "string",
      "proficiency": "Native|Fluent|Conversational|Basic|null"
    }
  ],
  "volunteer": [
    {
      "role": "string",
      "organization": "string",
      "location": "string|null",
      "start_date": "string|null",
      "end_date": "string|null",
      "bullets": ["string"]
    }
  ],
  "patents": [
    {
      "title": "string",
      "number": "string|null",
      "date": "string|null",
      "status": "Granted|Pending|null",
      "authors": "string|null"
    }
  ],
  "talks": [
    {
      "title": "string",
      "venue": "string|null",
      "date": "string|null",
      "type": "Conference|Workshop|Seminar|null"
    }
  ],
  "section_order": ["string"],
  "extra_sections": [
    {
      "title": "string",
      "content_type": "entries|text|list",
      "items": [
        {
          "header": "string|null",
          "subheader": "string|null",
          "bullets": ["string"],
          "text": "string|null"
        }
      ]
    }
  ]
}"""


_HEADER_INDICATORS = (
    "experience", "education", "projects", "skills", "certifications",
    "work history", "employment",
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


def _normalize_order(raw_order: list, extra_titles: list[str]) -> list[str]:
    """Map raw LLM section titles to canonical section keys.

    Known sections → their lowercase key ("Experience" → "experience").
    Titles matching an extra_sections title → "extra:<Title>".
    Anything unrecognized → dropped (prevents stale/hallucinated entries).
    """
    result = []
    seen_keys = set()
    for s in raw_order:
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


async def extract_resume(raw_text: str) -> Resume:
    user_prompt = f"Resume text:\n\n{raw_text[:8000]}"
    try:
        content = await _chat(
            [
                {"role": "system", "content": _EXTRACTION_SYSTEM},
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
                    {"role": "system", "content": _EXTRACTION_SYSTEM + "\nReturn ONLY the JSON object, no other text."},
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

    if isinstance(data, dict):
        extra_titles = [e.title for e in resume.extra_sections]
        resume.section_order = _normalize_order(data.get("section_order", []), extra_titles)

        # Ensure all populated standard sections are in the order somewhere
        # (prevents them from being invisible if the LLM forgot them in section_order)
        for key in [
            "summary", "experience", "education", "projects", "skills",
            "certifications", "publications", "awards", "languages",
            "volunteer", "patents", "talks",
        ]:
            val = getattr(resume, key, None)
            if val and key not in resume.section_order:
                resume.section_order.append(key)

        # Also ensure extra sections are included
        for extra in resume.extra_sections:
            extra_key = f"extra:{extra.title}"
            if extra_key not in resume.section_order:
                resume.section_order.append(extra_key)

    return resume
