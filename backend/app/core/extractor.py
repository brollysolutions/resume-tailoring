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
- Never invent dates, companies, titles, bullets, or skills that are not literally present in the source text.

Rules:
- Use the candidate's exact wording — do not paraphrase, do not add information that isn't there.
- If a field is missing from the resume, use null (for strings) or an empty array (for lists).
- For dates, preserve original formatting (e.g., "Aug 2020", "Jun 2025 – Dec 2025", "Present", "May 2024 - Current").
- Each bullet point becomes its own string. Strip leading bullet characters (•, -, –, *).
- For skills: if the resume groups skills under category labels (e.g., "Backend:", "Languages:"), use those category names. Otherwise put everything under category "Skills".
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
  "certifications": ["string"]
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
        return Resume.model_validate(data)
    except Exception as e:
        logger.exception(f"Schema validation failed, returning minimal Resume: {e}")
        # Never dump raw text into summary — that creates a fake Summary
        # section in every downstream render. Leave it null; the user can
        # re-upload if the parse was really that broken.
        name = (data.get("name") if isinstance(data, dict) else None) or "Unknown"
        return Resume(name=name)
