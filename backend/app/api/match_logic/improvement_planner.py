"""Prescriptive 'how to improve' plan for a scored resume.

Pure, LLM-free. Turns the diagnostic gap analysis into an impact-ranked list of
concrete actions, each tagged with an estimated score gain derived from the
keyword<->score coupling: every top-JD keyword the resume gains moves keyword
coverage by ~1/N, worth ~w_kw/N * 100 points (see hybrid_scorer._kw_signal).
"""
from __future__ import annotations

from typing import Optional

from app.core.keyword_utils import _top_jd_tokens
from app.api.match_logic.nlp_utils import extract_skills

# Sections a non-skill keyword can be steered into, worst-first preference.
_NARRATIVE_SECTIONS = ("Experience", "Projects", "Summary")

# Don't dump a wall of keywords into one action — cap to the most important few.
_MAX_KEYWORDS_PER_ACTION = 5


def _blocker_kind(reason: str) -> str:
    r = reason.lower()
    if "yr" in r or "year" in r:
        return "experience"
    if "degree" in r:
        return "education"
    if "level" in r:
        return "seniority"
    return "other"


def _lowest_narrative_section(section_scores: dict) -> str:
    """Pick the weakest narrative section that actually has content."""
    scored = [
        (s, section_scores[s])
        for s in _NARRATIVE_SECTIONS
        if section_scores.get(s) is not None
    ]
    if not scored:
        return "Experience"
    scored.sort(key=lambda x: x[1])
    return scored[0][0]


def _label(section: str, keywords: list[str]) -> str:
    quoted = ", ".join(f"'{k}'" for k in keywords)
    if section == "Skills":
        return f"Add {quoted} to Skills"
    return f"Work {quoted} into {section}"


def build_improvement_plan(
    jd_text: str,
    section_scores: dict,
    current_score: int,
    ceiling: Optional[dict],
    gap_analysis: Optional[dict],
    weights,
) -> dict:
    """Build the ranked improvement plan.

    Args:
        jd_text: Job description (for the top-JD denominator N).
        section_scores: {section: int|None}.
        current_score: the resume's current (tailored) match score.
        ceiling: detect_ceiling() output, or None.
        gap_analysis: compute_gap_analysis() output, or None.
        weights: active Weights (uses .w_kw for the marginal).

    Returns dict: current_score, achievable_ceiling, actions[], blockers[].
    """
    section_scores = section_scores or {}
    missing = list((gap_analysis or {}).get("missing_keywords") or [])

    # Per-keyword marginal effect on the score, from the keyword-coverage form.
    n = len(_top_jd_tokens(jd_text, k=30)) if jd_text else 0
    w_kw = float(getattr(weights, "w_kw", 0.0))
    per_kw = (w_kw / n) * 100.0 if n > 0 else 0.0

    # Split missing keywords into disjoint groups so a keyword is never counted
    # twice (keyword coverage is whole-resume — location only suggests WHERE).
    # `missing` arrives frequency-ranked, so the first few are the highest-impact.
    skill_kws: list[str] = []
    narrative_kws: list[str] = []
    for kw in missing:
        if extract_skills(kw):
            skill_kws.append(kw)
        else:
            narrative_kws.append(kw)
    skill_kws = skill_kws[:_MAX_KEYWORDS_PER_ACTION]
    narrative_kws = narrative_kws[:_MAX_KEYWORDS_PER_ACTION]

    # Skills first (most actionable, least noisy), then the weakest narrative
    # section. raw_gain is the nominal marginal effect on the keyword signal.
    candidates: list[dict] = []

    def _candidate(section: str, kws: list[str]) -> None:
        if not kws:
            return
        raw = max(1, round(len(kws) * per_kw)) if per_kw > 0 else 1
        candidates.append(
            {
                "kind": "add_keywords",
                "section": section,
                "keywords": kws,
                "raw_gain": raw,
                "label": _label(section, kws),
            }
        )

    _candidate("Skills", skill_kws)
    _candidate(_lowest_narrative_section(section_scores), narrative_kws)

    # Clip displayed gains so they never promise more than the headroom to 100.
    # achievable_ceiling stays consistent with the live score: it equals
    # current + the sum of the gains we actually show.
    actions: list[dict] = []
    remaining = max(0, 100 - current_score)
    for c in candidates:
        g = min(c["raw_gain"], remaining)
        if g <= 0:
            break
        actions.append(
            {
                "kind": c["kind"],
                "section": c["section"],
                "keywords": c["keywords"],
                "est_gain": g,
                "label": c["label"],
            }
        )
        remaining -= g

    achievable_ceiling = current_score + sum(a["est_gain"] for a in actions)

    # Hard-requirement gaps (years/degree/seniority) explain why even the ceiling
    # may sit below 100. Prose only — the live scorer doesn't apply these, so
    # baking them into the number would contradict the displayed score.
    blockers = [
        {"reason": r, "kind": _blocker_kind(r)}
        for r in ((ceiling or {}).get("reasons") or [])
    ]

    return {
        "current_score": current_score,
        "achievable_ceiling": achievable_ceiling,
        "actions": actions,
        "blockers": blockers,
    }
