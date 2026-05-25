"""Chat-style and interactive LLM functions for resume editing."""
import json
import logging
import re
from app.core.llm_client import _chat
from app.core.llm_synthesis import humanize_texts
from app.core.llm_prompts import PROMPT_CHAT_IMPROVE_ENTRY_SYSTEM

logger = logging.getLogger(__name__)

# Clean suggested text
_LEADING_MARKER_RE = re.compile(r'^\s*(?:[-•*—‒–·]+|\d+[.)])\s+')
_JD_PAREN_RE = re.compile(r'\s*\([^)]*\b(?:JD|Job Description|job description)\b[^)]*\)', re.IGNORECASE)
_INLINE_DASH_RE = re.compile(r'\s*[–—]\s*|\s+-\s+')
_COMPOUND_HYPHEN_RE = re.compile(r'(?<=\w)-(?=\w)')
_LABEL_PREFIX_RE = re.compile(r'^\s*(?:[SBM]\d+|Suggested|Original|New|Bullet)\s*:\s*', re.IGNORECASE)

_SECTION_RULES = """\
RULES:
- TENSE: SIMPLE PAST (built, designed, deployed, migrated). Never present.
- TONE: Professional. No contractions, filler, hedging, asides.
- Do NOT fabricate experience. Rephrase, reword, emphasize existing content.
- "suggested" is ONLY final replacement text — NO bullets, NO labels, NO JD commentary.
- Keep roughly same length as original.
- "original" MUST be verbatim copy.
- All rationale goes in "reasoning" ONLY.
- PRESERVE existing tech terms — don't swap for synonyms.
- MISSING JD KEYWORDS (when listed): treat as REQUIRED. Weave in 4–6 injections.
- Never invent experience to justify a keyword."""


def _clean_suggested(text: str) -> str:
    """Strip leading markers and JD commentary."""
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


async def regenerate_one_suggestion(
    section: str,
    original: str,
    previous_suggested: str,
    jd_text: str,
    mode: str = "replace",
) -> str:
    """Produce fresh alternative for single suggestion."""
    if mode == "add_skill" and section.lower().startswith("skill"):
        system = """You are an expert resume editor. Suggest a DIFFERENT single skill name
to add to the named category, drawn from JD requirements.
Return JSON: {"suggested": "<single skill name>"}.
- Must differ from previous suggestion.
- Must be plausibly required by JD."""
        user = (
            f"CATEGORY: {original}\n"
            f"PREVIOUS SUGGESTION: {previous_suggested}\n\n"
            f"JOB DESCRIPTION:\n{jd_text[:1500]}"
        )
    else:
        system = f"""You are an expert resume editor. Rewrite the line below to better match JD.

{_SECTION_RULES}

User wants a DIFFERENT angle. Your "suggested" MUST:
- Be substantively different from PREVIOUS SUGGESTION.
- Be roughly same length as ORIGINAL.
- Sound like real engineer wrote it.

Return JSON: {{"suggested": "<new replacement text>"}}."""
        user = (
            f"SECTION: {section}\n"
            f"ORIGINAL:\n{original}\n\n"
            f"PREVIOUS SUGGESTION:\n{previous_suggested}\n\n"
            f"JOB DESCRIPTION:\n{jd_text[:2000]}"
        )

    try:
        content = await _chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            json_mode=True,
        )
        parsed = json.loads(content)
        new_text = _clean_suggested(parsed.get("suggested", ""))
        if not new_text:
            return previous_suggested
        # Humanize narrative (skip Skills)
        if not section.lower().startswith("skill"):
            humanized = await humanize_texts([new_text])
            if humanized and humanized[0].strip():
                new_text = humanized[0].strip()
        return new_text
    except Exception as e:
        logger.warning(f"[regenerate_one_suggestion] failed: {e}")
        return previous_suggested


async def chat_improve_line(
    section: str,
    original_line: str,
    user_prompt: str,
    jd_text: str,
    resume_context: str,
    keywords_to_inject: list | None = None,
) -> str:
    """RAG-style rewrite of single line per user instruction, with JD keyword injection."""
    if not original_line.strip() or not user_prompt.strip():
        return original_line

    kw_block = ""
    if keywords_to_inject:
        kw_block = (
            "\n\nCRITICAL — JD KEYWORDS MISSING FROM THIS RESUME:\n"
            + ", ".join(keywords_to_inject[:15])
            + "\nWeave in as many of these as honestly applicable. Use the JD's exact terminology."
        )

    system = f"""You are an expert resume editor. Rewrite a resume line to better match the Job Description AND follow the user's instruction.

PRIMARY GOAL: Align the line with the Job Description keywords and requirements.
SECONDARY GOAL: Honor the user's specific instruction.

RULES:
- TENSE: simple past (built, designed, deployed, migrated). Never present tense.
- Use ONLY facts from RESUME CONTEXT. Do NOT fabricate metrics, employers, tech, or scale claims.
- Inject JD keywords listed below where honestly applicable — this is the main purpose.
- Single line, roughly same length unless user asked to expand/shrink.
- No leading bullets ("- ", "• "). Never join clauses with hyphens or en/em dashes ("-", "–", "—"); write clean, well-structured prose. Active voice only.
- No HR clichés ("leveraged", "spearheaded", "robust", "scalable", "cutting-edge").
{kw_block}

Return JSON: {{"rewritten": "<new line>"}}"""
    user = (
        f"JOB DESCRIPTION:\n{jd_text[:2000]}\n\n"
        f"RESUME CONTEXT (current state):\n{resume_context[:3000]}\n\n"
        f"SECTION: {section}\n"
        f"ORIGINAL LINE:\n{original_line}\n\n"
        f"USER INSTRUCTION:\n{user_prompt}"
    )
    try:
        content = await _chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            json_mode=True,
        )
        parsed = json.loads(content)
        new_text = _clean_suggested(parsed.get("rewritten", ""))
        return new_text or original_line
    except Exception as e:
        logger.warning(f"[chat_improve_line] failed: {e}")
        return original_line


async def chat_improve_entry(
    section: str,
    header_context: dict,
    original_bullets: list,
    user_prompt: str,
    jd_text: str,
    resume_context: str,
    keywords_to_inject: list | None = None,
) -> list:
    """RAG-style rewrite of entry's bullets as coherent unit.

    Returns exactly len(original_bullets) bullets. Missing positions fall back to original."""
    n = len(original_bullets)
    if n == 0 or not user_prompt.strip():
        return list(original_bullets)

    if section == "Projects":
        header_lines = (
            f"PROJECT NAME: {header_context.get('name', '')}\n"
            f"TECH: {header_context.get('tech', '') or ''}"
        )
    else:
        header_lines = (
            f"ROLE: {header_context.get('title', '')}\n"
            f"COMPANY: {header_context.get('company', '')}\n"
            f"DATES: {header_context.get('start_date', '')} – {header_context.get('end_date', '')}"
        )

    numbered_originals = "\n".join(
        f"{i+1}. {b}" for i, b in enumerate(original_bullets)
    )

    kw_block = ""
    if keywords_to_inject:
        kw_block = (
            "\n\nCRITICAL — JD KEYWORDS MISSING FROM THIS RESUME:\n"
            + ", ".join(keywords_to_inject[:15])
            + "\nAim to inject 3–5 of these across the rewritten bullets. Use the JD's exact terminology."
        )

    system = f"""You are an expert resume editor. Rewrite the bullets of ONE entry to better align with the Job Description AND follow the user's instruction.

PRIMARY GOAL: Align bullets with the Job Description keywords and requirements.
SECONDARY GOAL: Honor the user's specific instruction.

RULES:
- Return a list of bullets. You may change the number of bullets if the user asks you to condense, expand, or limit them (e.g., "keep to 3 bullets" or "condense into 1 bullet").
- STRICTLY follow constraints like "keep within 1 line" or "shorten to 20 words".
- TENSE: simple past for all bullets (built, designed, deployed, migrated, reduced). Never present tense.
- Use ONLY facts from RESUME CONTEXT. Do NOT fabricate metrics, employers, tech, or scale claims.
- Inject the JD keywords listed below where honestly applicable — this is the main purpose.
- Each bullet stands alone but the set reads coherently around the entry header.
- No leading bullets ("- ", "• "), no hyphens as inline separators, active voice only.
- No HR clichés ("leveraged", "spearheaded", "robust", "scalable", "cutting-edge").
{kw_block}

Return JSON: {{"bullets": ["<bullet 1>", "<bullet 2>", ...]}}."""

    user = (
        f"JOB DESCRIPTION (trimmed):\n{jd_text[:2000]}\n\n"
        f"RESUME CONTEXT (current state):\n{resume_context[:4000]}\n\n"
        f"SECTION: {section}\n"
        f"{header_lines}\n\n"
        f"ORIGINAL BULLETS (numbered, keep order):\n{numbered_originals}\n\n"
        f"USER INSTRUCTION:\n{user_prompt}"
    )
    try:
        content = await _chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            json_mode=True,
        )
        parsed = json.loads(content)
        raw = parsed.get("bullets", [])
        if not isinstance(raw, list):
            return list(original_bullets)
        cleaned = [_clean_suggested(str(x)) for x in raw]
        return cleaned
    except Exception as e:
        logger.warning(f"[chat_improve_entry] failed: {e}")
        return list(original_bullets)
