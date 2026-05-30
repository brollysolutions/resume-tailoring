"""Hybrid resume-JD scorer with 6 independently-calibrated signals.

Signals and default weights (sum = 1.0):
    w_kw    = 0.30  keyword coverage (req 70% / pref 30%)
    w_skill = 0.20  skill taxonomy coverage + domain alignment (60/40 blend)
    w_ngram = 0.10  multi-word skill matching (machine learning, ci/cd, etc.)
    w_edu   = 0.05  education / degree level fit
    w_sen   = 0.10  seniority (years-of-experience gap)
    w_cos   = 0.25  semantic cosine (whole-doc + experience section blend)

All weights are hot-swapped at runtime from weights_store.get_weights() so
the auto-calibrator can update them without a restart.

Raw sub-scores are logged to data/score_log.jsonl after every request so the
offline calibration harness (scripts/calibration/) can grid-search weights.
"""
from __future__ import annotations

import os
import json as _json
import hashlib as _hashlib
import logging
from dataclasses import dataclass, replace as _replace
from datetime import datetime as _datetime, timezone as _timezone
from pathlib import Path as _Path
from typing import Optional
from app.models.resume_schema import Resume

from app.core.keyword_utils import (
    parse_jd_required_preferred,
    extract_jd_ngrams,
    extract_resume_ngrams,
)
from app.core.skill_taxonomy import domain_alignment_score
from app.core.weights_store import get_weights, Weights
from .nlp_utils import keyword_coverage, extract_skills

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Degree hierarchy for education fit scoring
# ---------------------------------------------------------------------------
_DEGREE_LEVEL = {"associate": 1, "bachelor": 2, "master": 3, "phd": 4}

# R5: section weights for section-weighted cosine (replaces whole-doc cosine).
# Must match section names in section_scorer._SECTIONS.
_SECTION_COS_WEIGHTS: dict[str, float] = {
    "Skills": 0.40, "Experience": 0.35, "Projects": 0.20, "Summary": 0.05,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScoreInputs:
    resume_text: str
    resume_json: dict
    jd_text: str
    resume_embedding: Optional[list[float]] = None
    jd_embedding: Optional[list[float]] = None
    section_cosine: Optional[float] = None       # per-block max cosine (pre-remap)
    exp_section_cosine: Optional[float] = None   # experience section vs JD (pre-remap)
    resume_id: Optional[str] = None
    section_cosines: Optional[dict] = None       # R5: {section: raw_cosine} pre-remap
    resume_obj: Optional[Resume] = None          # Optional pre-parsed Resume object to avoid redundant validation


@dataclass
class RawSignals:
    req_kw: float
    pref_kw: float
    kw: float           # 0.7 * req_kw + 0.3 * pref_kw
    skill_cov: float    # taxonomy skill coverage
    domain_align: float
    skill: float        # 0.6 * skill_cov + 0.4 * domain_align
    ngram: float
    ngram_active: bool  # False when JD has no _NGRAM_SKILLS phrases (R4)
    edu: float
    seniority: float
    whole_doc_cos: float
    exp_cos: float
    cosine: float                              # primary cosine signal (post-remap)
    section_weighted_cos_raw: Optional[float]  # R5: pre-remap section-weighted avg (None = fallback)
    raw_whole_doc_cos: float
    raw_exp_cos: Optional[float]
    final_score: int


# ---------------------------------------------------------------------------
# Low-level utilities
# ---------------------------------------------------------------------------

def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = sum(x * x for x in vec_a) ** 0.5
    mag_b = sum(x * x for x in vec_b) ** 0.5
    if mag_a <= 0 or mag_b <= 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _resume_text_for_skills(resume_json: dict) -> str:
    parts: list[str] = []
    for sk in resume_json.get("skills", []) or []:
        parts.extend(sk.get("skills", []) or [])
    if resume_json.get("summary"):
        parts.append(resume_json["summary"])
    for exp in resume_json.get("experience", []) or []:
        parts.extend(exp.get("bullets", []) or [])
    for proj in resume_json.get("projects", []) or []:
        parts.extend(proj.get("bullets", []) or [])
        if proj.get("tech"):
            parts.append(proj["tech"])
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Per-signal extractors
# ---------------------------------------------------------------------------

def _kw_signal(jd_text: str, resume_text: str) -> tuple[float, float, float]:
    """(req_kw, pref_kw, blended_kw). Falls back to full-JD when no sections."""
    req_text, pref_text = parse_jd_required_preferred(jd_text)
    req_raw = keyword_coverage(req_text, resume_text)
    pref_raw = keyword_coverage(pref_text, resume_text) if pref_text else req_raw
    blended = 0.7 * req_raw + 0.3 * pref_raw
    return req_raw, pref_raw, blended


def _skill_signal(resume_json: dict, jd_text: str) -> tuple[float, float, float]:
    """(taxonomy_coverage, domain_alignment, blended_skill)."""
    jd_skills = extract_skills(jd_text)
    if not jd_skills:
        return 0.0, 1.0, 0.6  # neutral when JD has no recognisable skills

    resume_skill_text = _resume_text_for_skills(resume_json)
    resume_skills = extract_skills(resume_skill_text)

    matched = jd_skills & resume_skills
    unmatched_jd = jd_skills - matched

    from app.core.skill_taxonomy import domain_of
    resume_domains = {d for d in (domain_of(s) for s in resume_skills) if d}
    half_credit = sum(0.5 for s in unmatched_jd if domain_of(s) in resume_domains)
    taxonomy_cov = min((len(matched) + half_credit) / len(jd_skills), 1.0)

    domain_align = domain_alignment_score(resume_json, jd_text)
    blended = 0.6 * taxonomy_cov + 0.4 * domain_align
    return taxonomy_cov, domain_align, blended


def _ngram_signal(jd_text: str, resume_text: str) -> tuple[float, bool]:
    """(coverage, active). Fraction of multi-word JD skills found in resume.

    active=False when the JD contains no _NGRAM_SKILLS phrases. Callers must
    redistribute w_ngram into another weight rather than rewarding the row
    with a sentinel 1.0 (R4 — see findings_summary.md).
    """
    jd_ngrams = extract_jd_ngrams(jd_text)
    if not jd_ngrams:
        return 0.0, False
    resume_ngrams = extract_resume_ngrams(resume_text)
    matched = jd_ngrams & resume_ngrams
    return len(matched) / len(jd_ngrams), True


def _edu_signal(resume_json: dict, jd_text: str, resume_obj: Optional[Resume] = None) -> float:
    """[0, 1] education fit. 1.0 when JD states no degree requirement."""
    from app.api.match_logic.ceiling_detector import parse_jd_hard_requirements, resume_has_degree
    from app.models.resume_schema import Resume

    hard_reqs = parse_jd_hard_requirements(jd_text)
    required = hard_reqs.get("required_degrees", [])
    if not required:
        return 1.0

    if resume_obj is None:
        try:
            resume_obj = Resume.model_validate(resume_json)
        except Exception:
            return 0.7

    if resume_has_degree(resume_obj, required):
        return 1.0

    jd_level = max((_DEGREE_LEVEL.get(d, 0) for d in required), default=0)
    edu_blob = " ".join(
        f"{e.degree or ''} {e.field or ''}".lower()
        for e in resume_obj.education
    )
    resume_level = max(
        (lvl for kw, lvl in _DEGREE_LEVEL.items() if kw in edu_blob),
        default=0,
    )
    if resume_level >= jd_level:
        return 1.0
    gap = jd_level - resume_level
    return max(0.3, 1.0 - gap * 0.25)


def _seniority_signal(resume_json: dict, jd_text: str, resume_obj: Optional[Resume] = None) -> float:
    """[0, 1] seniority fit. 1.0 when JD states no requirements.

    Blends years-of-experience and seniority title matching.
    """
    from app.api.match_logic.ceiling_detector import (
        parse_jd_hard_requirements,
        estimate_years_experience,
        infer_seniority,
        _SENIORITY_ORDER,
    )
    from app.models.resume_schema import Resume

    hard_reqs = parse_jd_hard_requirements(jd_text)
    jd_years = hard_reqs.get("min_years_experience")
    jd_level = hard_reqs.get("seniority_level")

    if not jd_years and not jd_level:
        return 1.0

    if resume_obj is None:
        try:
            resume_obj = Resume.model_validate(resume_json)
        except Exception:
            return 0.7

    scores = []

    # Years-of-experience signal
    if jd_years:
        resume_yrs = estimate_years_experience(resume_obj)
        if resume_yrs is not None:
            scores.append(min(1.0, resume_yrs / jd_years))
        else:
            scores.append(0.5)  # neutral-low if years expected but none parsed

    # Seniority title signal
    if jd_level in _SENIORITY_ORDER:
        candidate_level = infer_seniority(resume_obj)
        req_idx = _SENIORITY_ORDER.index(jd_level)
        candidate_idx = _SENIORITY_ORDER.index(candidate_level) if candidate_level in _SENIORITY_ORDER else 1  # default to mid
        
        # Calculate title penalty only when falling short
        gap = max(0, req_idx - candidate_idx)
        title_score = max(0.0, min(1.0, 1.0 - gap * 0.25))
        scores.append(title_score)

    if not scores:
        return 0.7
    return sum(scores) / len(scores)


def _cosine_signal(
    inputs: ScoreInputs,
    p_low: float,
    p_high: float,
) -> tuple[float, float, float, Optional[float], float, Optional[float]]:
    """(whole_doc_cos, exp_cos, blended, section_weighted_raw, raw_whole_doc_cos, raw_exp_cos).

    All cosines post-remap [0, 1] for first 3.
    """
    remap_span = max(p_high - p_low, 1e-6)

    # whole_doc preserved for logging backward compat
    whole_doc = 0.0
    raw_whole_doc = 0.0
    if inputs.resume_embedding and inputs.jd_embedding:
        try:
            raw_whole_doc = _cosine_similarity(inputs.resume_embedding, inputs.jd_embedding)
            whole_doc = max(0.0, min(1.0, (raw_whole_doc - p_low) / remap_span))
        except Exception as e:
            logger.warning("Whole-doc cosine failed: %s", e)

    # Experience cosine (kept for logging)
    exp_cos_remapped = 0.0
    raw_exp_cos = inputs.exp_section_cosine
    if raw_exp_cos is not None:
        exp_cos_remapped = max(0.0, min(1.0, (raw_exp_cos - p_low) / remap_span))

    # R5: section-weighted cosine as primary signal
    section_weighted_raw: Optional[float] = None
    if inputs.section_cosines:
        total_w = sum(
            w for s, w in _SECTION_COS_WEIGHTS.items() if s in inputs.section_cosines
        )
        if total_w > 0:
            section_weighted_raw = sum(
                inputs.section_cosines[s] * w
                for s, w in _SECTION_COS_WEIGHTS.items()
                if s in inputs.section_cosines
            ) / total_w

    if section_weighted_raw is not None:
        blended = max(0.0, min(1.0, (section_weighted_raw - p_low) / remap_span))
    elif inputs.exp_section_cosine is not None and inputs.resume_embedding:
        blended = 0.5 * whole_doc + 0.5 * exp_cos_remapped
    elif inputs.section_cosine is not None and inputs.resume_embedding:
        section_cos = max(0.0, min(1.0, (inputs.section_cosine - p_low) / remap_span))
        blended = 0.5 * whole_doc + 0.5 * section_cos
    elif inputs.exp_section_cosine is not None:
        blended = exp_cos_remapped
    elif inputs.section_cosine is not None:
        blended = max(0.0, min(1.0, (inputs.section_cosine - p_low) / remap_span))
    else:
        blended = whole_doc

    return whole_doc, exp_cos_remapped, blended, section_weighted_raw, raw_whole_doc, raw_exp_cos


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def compute_signals(
    inputs: ScoreInputs,
    weights: Optional[Weights] = None,
    p_low_override: Optional[float] = None,
    p_high_override: Optional[float] = None,
) -> RawSignals:
    """Compute all 6 raw signals. Pure (no I/O, no side effects).

    Accepts an optional weights override so per-section scoring can use a
    different blend than the global calibrated weights.
    """
    if weights is None:
        weights = get_weights()

    # Use overrides for cosine remapping if provided (Signal R5 section scoring)
    p_low = p_low_override if p_low_override is not None else weights.p_low
    p_high = p_high_override if p_high_override is not None else weights.p_high

    req_kw, pref_kw, kw = _kw_signal(inputs.jd_text, inputs.resume_text)
    skill_cov, domain_align, skill = _skill_signal(inputs.resume_json, inputs.jd_text)
    ngram, ngram_active = _ngram_signal(inputs.jd_text, inputs.resume_text)
    edu = _edu_signal(inputs.resume_json, inputs.jd_text, inputs.resume_obj)
    seniority = _seniority_signal(inputs.resume_json, inputs.jd_text, inputs.resume_obj)
    whole_doc_cos, exp_cos, cosine, section_weighted_raw, raw_whole_doc_cos, raw_exp_cos = _cosine_signal(inputs, p_low, p_high)

    if ngram_active:
        raw = (
            kw * weights.w_kw
            + skill * weights.w_skill
            + ngram * weights.w_ngram
            + edu * weights.w_edu
            + seniority * weights.w_sen
            + cosine * weights.w_cos
        )
    else:
        # R4: JD has no n-gram phrases — redistribute w_ngram into w_kw so the
        # row isn't penalized for an unavailable signal AND isn't falsely
        # boosted by the prior 1.0 sentinel.
        raw = (
            kw * (weights.w_kw + weights.w_ngram)
            + skill * weights.w_skill
            + edu * weights.w_edu
            + seniority * weights.w_sen
            + cosine * weights.w_cos
        )
    final_score = int(round(max(0.0, min(1.0, raw)) * 100))

    return RawSignals(
        req_kw=req_kw,
        pref_kw=pref_kw,
        kw=kw,
        skill_cov=skill_cov,
        domain_align=domain_align,
        skill=skill,
        ngram=ngram,
        ngram_active=ngram_active,
        edu=edu,
        seniority=seniority,
        whole_doc_cos=whole_doc_cos,
        exp_cos=exp_cos,
        cosine=cosine,
        section_weighted_cos_raw=section_weighted_raw,
        raw_whole_doc_cos=raw_whole_doc_cos,
        raw_exp_cos=raw_exp_cos,
        final_score=final_score,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_resume_against_jd(
    resume_text: str,
    resume_json: dict,
    jd_text: str,
    resume_embedding: Optional[list[float]] = None,
    jd_embedding: Optional[list[float]] = None,
    section_cosine: Optional[float] = None,
    exp_section_cosine: Optional[float] = None,
    resume_id: Optional[str] = None,
    weights_override: Optional[dict] = None,
    log_event: bool = True,
    ceiling: Optional[dict] = None,
    hard_reqs: Optional[dict] = None,
    section_cosines: Optional[dict] = None,
    resume_obj: Optional[Resume] = None,
    p_low_override: Optional[float] = None,
    p_high_override: Optional[float] = None,
) -> dict:
    """Score a resume against a JD. Returns score + breakdown + feature_contributions.

    Backward-compatible signature — callers that only pass the first 3 args
    still work; new callers can pass exp_section_cosine for a richer signal.

    weights_override: dict with any subset of w_kw/w_skill/w_ngram/w_edu/w_sen/w_cos
        to override the active calibrated weights (used by per-section scoring).
    log_event: when False, skip writing to score_log.jsonl (use for per-section
        scoring so calibration is not polluted by partial-text events).
    p_low_override / p_high_override: Manually override the cosine remapping bounds
        (useful for section scoring where raw cosines are naturally lower).
    """
    weights = get_weights()
    if weights_override:
        overrides = {
            k: float(v) for k, v in weights_override.items()
            if k in ("w_kw", "w_skill", "w_ngram", "w_edu", "w_sen", "w_cos")
        }
        if overrides:
            weights = _replace(weights, **overrides)

    inputs = ScoreInputs(
        resume_text=resume_text,
        resume_json=resume_json,
        jd_text=jd_text,
        resume_embedding=resume_embedding,
        jd_embedding=jd_embedding,
        section_cosine=section_cosine,
        exp_section_cosine=exp_section_cosine,
        resume_id=resume_id,
        section_cosines=section_cosines,
        resume_obj=resume_obj,
    )
    signals = compute_signals(
        inputs,
        weights,
        p_low_override=p_low_override,
        p_high_override=p_high_override,
    )
    if log_event:
        _log_score_event(signals, resume_id, jd_text, ceiling=ceiling, hard_reqs=hard_reqs)

    return {
        "score": signals.final_score,
        "breakdown": {
            "bm25": int(round(signals.kw * 100)),
            "semantic": int(round(signals.cosine * 100)),
            "skill_coverage": int(round(signals.skill_cov * 100)),
            "domain_alignment": int(round(signals.domain_align * 100)),
            "ngram": int(round(signals.ngram * 100)),
            "education": int(round(signals.edu * 100)),
            "seniority": int(round(signals.seniority * 100)),
        },
        # Per-feature raw contributions (0-100). Useful for showing users
        # *why* a section scored low (e.g., "kw=32, cosine=58, ngram=15").
        "feature_contributions": {
            "keyword": int(round(signals.kw * 100)),
            "skill": int(round(signals.skill * 100)),
            "ngram": int(round(signals.ngram * 100)),
            "edu": int(round(signals.edu * 100)),
            "seniority": int(round(signals.seniority * 100)),
            "cosine": int(round(signals.cosine * 100)),
        },
        "weights_used": {
            "w_kw": weights.w_kw,
            "w_skill": weights.w_skill,
            "w_ngram": weights.w_ngram,
            "w_edu": weights.w_edu,
            "w_sen": weights.w_sen,
            "w_cos": weights.w_cos,
        },
        # R4: surface for section_scorer logging so per-section events can
        # record ngram_active alongside ngram_coverage.
        "ngram_active": signals.ngram_active,
    }


# ---------------------------------------------------------------------------
# Score event logging
# ---------------------------------------------------------------------------

_SCORE_LOG_PATH = _Path(__file__).resolve().parents[3] / "data" / "score_log.jsonl"


def _log_score_event(
    signals: RawSignals,
    resume_id: Optional[str],
    jd_text: str,
    ceiling: Optional[dict] = None,
    hard_reqs: Optional[dict] = None,
) -> None:
    """Best-effort append to score_log.jsonl. Never raises."""
    if os.environ.get("TESTING") == "1":
        return
    try:
        _SCORE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        excerpt = (jd_text or "")[:240].replace("\n", " ").strip()
        c = ceiling or {}
        hr = hard_reqs or {}
        
        # Log active calibration anchors at the time of matching
        weights = get_weights()
        p_low = weights.p_low
        p_high = weights.p_high

        event = {
            "ts": _datetime.now(_timezone.utc).isoformat(),
            "resume_id": resume_id,
            "jd_hash": _hashlib.sha256(jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16],
            "jd_excerpt": excerpt,
            # Keyword signals
            "req_kw_raw": round(signals.req_kw, 4),
            "pref_kw_raw": round(signals.pref_kw, 4),
            "kw_raw": round(signals.kw, 4),
            # Skill signals
            "skill_raw": round(signals.skill_cov, 4),
            "domain_raw": round(signals.domain_align, 4),
            # N-gram signal. R4 deprecation path: ngram_raw keeps the legacy
            # 1.0-sentinel-when-inactive semantic so audit scripts (s2/s3/s4/s5/
            # s7/s8/s9) keep producing identical numbers; ngram_coverage carries
            # the corrected 0.0-when-inactive value; ngram_active gates which
            # rows actually have a measurable signal.
            "ngram_raw": round(1.0 if not signals.ngram_active else signals.ngram, 4),
            "ngram_coverage": round(signals.ngram, 4),
            "ngram_active": signals.ngram_active,
            # Education and seniority
            "edu_raw": round(signals.edu, 4),
            "seniority_raw": round(signals.seniority, 4),
            # Cosine signals: write true raw whole-doc/exp values
            "whole_doc_cos_raw": round(signals.raw_whole_doc_cos, 4),
            "exp_cos_raw": round(signals.raw_exp_cos, 4) if signals.raw_exp_cos is not None else None,
            "cosine_blended": round(signals.cosine, 4),
            "section_weighted_cos_raw": round(signals.section_weighted_cos_raw, 4) if signals.section_weighted_cos_raw is not None else None,
            "final_score": signals.final_score,
            # Calibration anchors active at runtime
            "p_low": round(p_low, 4),
            "p_high": round(p_high, 4),
            # Ceiling outcome (R2). Null when ceiling not computed (legacy
            # callers, per-section log path).
            "ceiling_score": c.get("score"),
            "ceiling_reasons": c.get("reasons") or [],
            "exp_required": c.get("exp_required"),
            "exp_actual": c.get("exp_actual"),
            # Raw JD hard-requirement extraction (R2). Lets audits avoid
            # re-running parse_jd_hard_requirements on the truncated excerpt.
            "extracted_min_years": hr.get("min_years_experience"),
            "extracted_degrees": hr.get("required_degrees") or [],
            "extracted_seniority": hr.get("seniority_level"),
        }
        with _SCORE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(event) + "\n")
    except Exception as e:
        logger.debug("Score log write failed: %s", e)


# ---------------------------------------------------------------------------
# Legacy diagnostic (kept for UI compatibility)
# ---------------------------------------------------------------------------

def diagnose_score(score: int, breakdown: dict, section_scores: dict, ceiling: dict) -> dict:
    """Classify why a score is low or stuck and suggest a highly specific, actionable remedy."""
    import re

    # 1. High match / good matches
    if score >= 85:
        return {
            "code": "excellent",
            "headline": "Outstanding Match!",
            "detail": "Your resume is exceptionally well-aligned with this job description across experience, skills, and background."
        }
    elif score >= 75:
        return {
            "code": "good",
            "headline": "Strong Match with High Potential",
            "detail": "You have a very solid profile for this role. A few minor tweaks to your keywords or experience descriptions can push it even higher."
        }

    # 2. Extract ceiling reasons
    reasons = ceiling.get("reasons") or []
    
    # Check Years of Experience gap
    exp_required = ceiling.get("exp_required")
    exp_actual = ceiling.get("exp_actual")
    if (
        isinstance(exp_required, (int, float)) and exp_required > 0
        and exp_actual is not None
        and exp_actual + 0.5 < exp_required
    ):
        return {
            "code": "experience_gap",
            "headline": f"Experience Gap: JD requires {exp_required}+ years",
            "detail": (
                f"Your resume shows ~{exp_actual:g} years of experience. This experience gap is placing a ceiling on your match score. "
                "Highlight transferable skills, intensive projects, or relevant training to offset this gap."
            )
        }

    # Check Seniority Mismatch
    for r in reasons:
        if r.startswith("targets "):
            target_level = "Senior"
            resume_level = "Mid"
            m = re.search(r"targets ([a-z]+) level(?: \(resume reads ([a-z]+)\))?", r)
            if m:
                target_level = m.group(1).capitalize()
                if m.group(2):
                    resume_level = m.group(2).capitalize()
                else:
                    resume_level = "Junior/Mid"
            return {
                "code": "seniority_title_gap",
                "headline": f"Seniority Mismatch: JD targets {target_level} level",
                "detail": (
                    f"Your resume's most recent job title is inferred at the {resume_level} level, which falls short of the target. "
                    "Adjust your job titles or emphasize leadership, mentorship, and architecture responsibilities to align with this level."
                )
            }

    # Check Required Degree Gap
    for r in reasons:
        if r.startswith("requires ") and "degree" in r:
            degree_str = r.replace("requires ", "").replace(" degree", "")
            degree_display = degree_str.capitalize()
            return {
                "code": "degree_gap",
                "headline": f"Education Mismatch: Missing {degree_display} Degree",
                "detail": (
                    f"The job description specifies a required {degree_str} degree that isn't explicitly detected on your resume. "
                    "If you have this degree or equivalent, make sure it is clearly listed in your Education section."
                )
            }

    # 3. Soft deficits (Skills, Keywords, Semantics)
    bm25 = breakdown.get("bm25", 0)
    skill_coverage = breakdown.get("skill_coverage", 0)
    semantic = breakdown.get("semantic", 0)

    # Sort soft deficits to find the absolute lowest scoring area
    soft_deficits = [
        ("low_keywords", bm25, "Low Keyword Overlap", 
         f"Your resume is missing several core keywords from the job description (keyword match is at {bm25}%). Use the 'Tailor' tab to accept suggestions and inject these missing terms seamlessly."),
        ("low_skills", skill_coverage, "Skill Taxonomy Gap", 
         f"Your profile lacks key technical or domain-specific skills required for this role (skill coverage is at {skill_coverage}%). Adding these specific skills to your Skills section will significantly improve alignment."),
        ("low_semantic", semantic, "Low Semantic Alignment", 
         f"The phrasing and overall focus of your experience descriptions don't closely align with the JD's theme (semantic match is at {semantic}%). Re-writing experience bullets to focus on the JD's primary outcomes will boost this.")
    ]

    lowest_deficit = min(soft_deficits, key=lambda x: x[1])
    if lowest_deficit[1] < 60:
        return {
            "code": lowest_deficit[0],
            "headline": lowest_deficit[2],
            "detail": lowest_deficit[3]
        }

    # 4. Fallback / General low score
    return {
        "code": "low_general",
        "headline": "General Tailoring Recommended",
        "detail": (
            f"Your current match score is {score}%. While you have a solid foundation, general tailoring of your resume "
            "to match the job description will elevate your standing. Review the suggestions in the Tailor tab to begin."
        )
    }

