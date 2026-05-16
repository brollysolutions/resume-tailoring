"""Gap analysis: identify missing JD keywords per resume section."""

from app.core.keyword_utils import _significant_tokens, _top_jd_tokens, _fuzzy_coverage
from app.api.match_logic.section_scorer import _section_text

_SECTIONS = ("Experience", "Projects", "Skills", "Summary")


def compute_gap_analysis(resume_obj, resume_text: str, jd_text: str, section_scores: dict) -> dict:
    """Analyze score gaps: identify missing keywords overall and per-section.

    Args:
        resume_obj: Resume object
        resume_text: Plaintext resume
        jd_text: Job description text
        section_scores: Dict of section → score (from compute_section_scores)

    Returns:
        {
            "missing_keywords": [...],  # top missing keywords overall
            "section_gaps": {
                "Experience": [...],
                "Projects": [...],
                ...
            },
            "low_sections": [
                { "section": "Experience", "score": 35, "reason": "...", "top_missing": [...] },
                ...
            ]
        }
    """
    top_jd = _top_jd_tokens(jd_text, k=30)
    resume_toks = _significant_tokens(resume_text)
    covered = _fuzzy_coverage(top_jd, resume_toks)
    missing_overall = sorted(top_jd - covered)[:15]

    # Per-section missing keywords
    section_gaps: dict[str, list[str]] = {}
    for section in _SECTIONS:
        text = _section_text(resume_obj, section)
        if not text.strip():
            continue
        toks = _significant_tokens(text)
        sect_covered = _fuzzy_coverage(top_jd, toks)
        section_gaps[section] = sorted(top_jd - sect_covered)[:8]

    # Identify low-scoring sections with reasons (fallback text; the AI-driven
    # `explanation` field is populated by the match endpoint after this call).
    low_sections = []
    for section in _SECTIONS:
        score = section_scores.get(section)
        if score is None or score >= 65:
            continue
        if score < 40:
            reason = "Low keyword density — add more JD-relevant content to this section"
        elif score < 55:
            reason = "Partial match — keywords present but lacking context and depth"
        else:
            reason = "Close — a few more keyword mentions would push this section above threshold"
        low_sections.append({
            "section": section,
            "score": score,
            "reason": reason,
            "explanation": "",
        })

    # Sort worst sections first
    low_sections.sort(key=lambda x: x["score"])

    return {
        "missing_keywords": missing_overall,
        "section_gaps": section_gaps,
        "low_sections": low_sections,
    }
