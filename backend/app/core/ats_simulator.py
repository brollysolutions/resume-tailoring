"""ATS (Applicant Tracking System) simulator.

Rule-based checks (field detection, section recognition, format warnings) plus
an LLM post-filter that strips non-skill noise from the missing-keyword list
before showing it to the user.
"""
from __future__ import annotations

import json
import logging

from app.models.resume_schema import Resume
from app.core.renderer import resume_to_plaintext, _resume_char_count
from app.core.keyword_utils import _top_jd_tokens, _significant_tokens, _fuzzy_coverage
from app.core.llm_client import _chat, get_model_name

logger = logging.getLogger(__name__)


def _detect_missing_fields(resume: Resume) -> list[str]:
    missing: list[str] = []
    if not (resume.name or "").strip():
        missing.append("name")
    c = resume.contact
    if not (getattr(c, "email", None) or "").strip():
        missing.append("email")
    if not (getattr(c, "phone", None) or "").strip():
        missing.append("phone")
    if not (getattr(c, "linkedin", None) or "").strip():
        missing.append("linkedin")
    if not (getattr(c, "github", None) or "").strip():
        missing.append("github")
    return missing


def _check_section_recognition(resume: Resume) -> dict[str, bool]:
    result = {
        "experience": bool(resume.experience),
        "education": bool(resume.education),
        "skills": bool(resume.skills),
        "summary": bool(resume.summary),
        "projects": bool(resume.projects),
        "certifications": bool(resume.certifications),
    }
    critical = {"experience", "skills"}
    return {k: v for k, v in result.items() if k in critical or v}


def _detect_format_warnings(resume: Resume) -> list[str]:
    warnings: list[str] = []
    for sec in (resume.extra_sections or []):
        if sec.content_type == "entries":
            warnings.append(
                f'Custom section "{sec.title}" uses entry format — some ATS parsers may skip it'
            )
        elif sec.content_type == "text":
            for item in (sec.items or []):
                if item.text and "\n" in item.text:
                    warnings.append(
                        f'Free-text block in "{sec.title}" may be ignored by ATS'
                    )
                    break
    if _resume_char_count(resume) > 8000:
        warnings.append("Resume may exceed 2 pages — ATS often truncates after page 2")
    if "skills" in (resume.hidden_sections or []):
        warnings.append("Skills section is hidden — ATS cannot extract your skills")
    return warnings


def _compute_keyword_coverage(
    resume: Resume, jd_text: str
) -> tuple[list[str], list[str], int]:
    top_jd = _top_jd_tokens(jd_text, k=20)
    if not top_jd:
        return [], [], 0
    plaintext = resume_to_plaintext(resume)
    resume_tokens = _significant_tokens(plaintext)
    found_set = _fuzzy_coverage(top_jd, resume_tokens)
    missing = sorted(top_jd - found_set)
    found = sorted(found_set)
    score = int(len(found) / max(len(top_jd), 1) * 100)
    return found, missing, score


def _compute_parse_score(
    missing_fields: list[str],
    format_warnings: list[str],
) -> int:
    score = 100
    field_penalties = {"name": 20, "email": 20, "phone": 15, "linkedin": 8, "github": 7}
    for f in missing_fields:
        score -= field_penalties.get(f, 5)
    score -= min(len(format_warnings) * 10, 20)
    return max(0, min(100, score))


async def _llm_filter_actionable_keywords(
    candidates: list[str], jd_text: str
) -> list[str]:
    """Post-filter extracted JD tokens to only genuine tech skills.

    `_top_jd_tokens` is designed for scoring speed — it uses a static blocklist.
    This LLM call is the contextual layer that removes EEO boilerplate, soft skills,
    generic nouns, etc. that the static list misses. Called only from run_ats_check
    (user-triggered, not on every match request).

    Falls back to the original list on any error — never blocks the ATS check.
    """
    if not candidates:
        return candidates
    prompt = (
        "Filter this list of tokens extracted from a job description. "
        "Return ONLY tokens that are genuine tech skills, tools, frameworks, "
        "programming languages, platforms, or specific technical domain concepts "
        "that a candidate should add to their resume.\n\n"
        "EXCLUDE: generic nouns (app, computer, area, system), soft skills "
        "(deadline, feedback, efficiency, communication), EEO/legal terms "
        "(citizenship, disability, age, equal), education words (degree, gpa), "
        "business language (status, consumer, content, payment, revenue), "
        "action verbs (explore, drive, enable), or any word that would look "
        "out of place in a resume skills section.\n\n"
        f"JD context (first 400 chars):\n{jd_text[:400]}\n\n"
        f"Tokens to filter: {json.dumps(candidates)}\n\n"
        'Return JSON: {"actionable": ["token1", "token2", ...]}'
    )
    try:
        raw = await _chat(
            [{"role": "user", "content": prompt}],
            json_mode=True,
            model=get_model_name(),
            use_cache=True,
        )
        result = json.loads(raw)
        filtered = result.get("actionable", candidates)
        valid = set(candidates)
        return [t for t in filtered if t in valid]
    except Exception as e:
        logger.warning("[ATS] LLM keyword filter failed (%s) — using raw list", e)
        return candidates


def _build_action_suggestions(
    missing_fields: list[str],
    missing_keywords: list[str],
    format_warnings: list[str],
) -> list[dict]:
    suggestions: list[dict] = []
    for f in missing_fields:
        suggestions.append({
            "action": "add_field",
            "target": f,
            "reason": f"ATS requires {f} to contact you",
        })
    for kw in missing_keywords[:5]:
        suggestions.append({
            "action": "tailor_section",
            "target": kw,
            "reason": f'Add "{kw}" to your resume to match the JD',
        })
    for w in format_warnings:
        suggestions.append({
            "action": "restructure",
            "target": w,
            "reason": w,
        })
    return suggestions


async def run_ats_check(resume: Resume, jd_text: str) -> dict:
    missing_fields = _detect_missing_fields(resume)
    section_recognition = _check_section_recognition(resume)
    format_warnings = _detect_format_warnings(resume)

    found_keywords, missing_keywords, _ = _compute_keyword_coverage(resume, jd_text)

    # LLM post-filter: strip non-skill noise before showing to user
    all_actionable = await _llm_filter_actionable_keywords(
        found_keywords + missing_keywords, jd_text
    )
    actionable_set = set(all_actionable)
    found_keywords = [k for k in found_keywords if k in actionable_set]
    missing_keywords = [k for k in missing_keywords if k in actionable_set]
    total = len(found_keywords) + len(missing_keywords)
    keyword_score = int(len(found_keywords) / max(total, 1) * 100)

    parse_score = _compute_parse_score(missing_fields, format_warnings)
    action_suggestions = _build_action_suggestions(missing_fields, missing_keywords, format_warnings)
    return {
        "parse_score": parse_score,
        "keyword_score": keyword_score,
        "section_recognition": section_recognition,
        "format_warnings": format_warnings,
        "missing_fields": missing_fields,
        "found_keywords": found_keywords,
        "missing_keywords": missing_keywords,
        "suggestions": action_suggestions,
    }
