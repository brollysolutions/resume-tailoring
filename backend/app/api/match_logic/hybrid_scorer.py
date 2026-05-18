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

import json as _json
import hashlib as _hashlib
import logging
from dataclasses import dataclass
from datetime import datetime as _datetime, timezone as _timezone
from pathlib import Path as _Path
from typing import Optional

from app.core.keyword_utils import (
    parse_jd_required_preferred,
    extract_jd_ngrams,
    extract_resume_ngrams,
)
from app.core.skill_taxonomy import domain_alignment_score
from app.core.weights_store import get_weights
from .nlp_utils import keyword_coverage, extract_skills

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Degree hierarchy for education fit scoring
# ---------------------------------------------------------------------------
_DEGREE_LEVEL = {"associate": 1, "bachelor": 2, "master": 3, "phd": 4}


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


@dataclass
class RawSignals:
    req_kw: float
    pref_kw: float
    kw: float           # 0.7 * req_kw + 0.3 * pref_kw
    skill_cov: float    # taxonomy skill coverage
    domain_align: float
    skill: float        # 0.6 * skill_cov + 0.4 * domain_align
    ngram: float
    edu: float
    seniority: float
    whole_doc_cos: float
    exp_cos: float
    cosine: float       # blended cosine signal (post-remap)
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


def _ngram_signal(jd_text: str, resume_text: str) -> float:
    """Fraction of multi-word JD skills found in resume. 1.0 when JD has none."""
    jd_ngrams = extract_jd_ngrams(jd_text)
    if not jd_ngrams:
        return 1.0
    resume_ngrams = extract_resume_ngrams(resume_text)
    matched = jd_ngrams & resume_ngrams
    return len(matched) / len(jd_ngrams)


def _edu_signal(resume_json: dict, jd_text: str) -> float:
    """[0, 1] education fit. 1.0 when JD states no degree requirement."""
    from app.api.match_logic.ceiling_detector import parse_jd_hard_requirements, resume_has_degree
    from app.models.resume_schema import Resume

    hard_reqs = parse_jd_hard_requirements(jd_text)
    required = hard_reqs.get("required_degrees", [])
    if not required:
        return 1.0

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


def _seniority_signal(resume_json: dict, jd_text: str) -> float:
    """[0, 1] seniority fit. 1.0 when JD states no years requirement.

    Uses ceiling_detector.estimate_years_experience() which correctly merges
    overlapping experience spans (handles concurrent roles).
    """
    from app.api.match_logic.ceiling_detector import parse_jd_hard_requirements, estimate_years_experience
    from app.models.resume_schema import Resume

    hard_reqs = parse_jd_hard_requirements(jd_text)
    jd_years = hard_reqs.get("min_years_experience")
    if not jd_years:
        return 1.0

    try:
        resume_obj = Resume.model_validate(resume_json)
        resume_yrs = estimate_years_experience(resume_obj)
    except Exception:
        return 0.7

    if resume_yrs is None:
        return 0.7
    return min(1.0, resume_yrs / jd_years)


def _cosine_signal(
    inputs: ScoreInputs,
    p_low: float,
    p_high: float,
) -> tuple[float, float, float]:
    """(whole_doc_cos, exp_cos, blended). All values post-remap [0, 1]."""
    remap_span = max(p_high - p_low, 1e-6)

    whole_doc = 0.0
    if inputs.resume_embedding and inputs.jd_embedding:
        try:
            raw = _cosine_similarity(inputs.resume_embedding, inputs.jd_embedding)
            whole_doc = max(0.0, min(1.0, (raw - p_low) / remap_span))
        except Exception as e:
            logger.warning("Whole-doc cosine failed: %s", e)

    # Section max cosine (per-block, kept for backward compat)
    section_cos = 0.0
    if inputs.section_cosine is not None:
        section_cos = max(0.0, min(1.0, (inputs.section_cosine - p_low) / remap_span))

    # Experience section cosine
    exp_cos_remapped = 0.0
    if inputs.exp_section_cosine is not None:
        exp_cos_remapped = max(0.0, min(1.0, (inputs.exp_section_cosine - p_low) / remap_span))

    # Blend: prefer exp_section_cosine over section_max when available
    if inputs.exp_section_cosine is not None and inputs.resume_embedding:
        blended = 0.5 * whole_doc + 0.5 * exp_cos_remapped
    elif inputs.section_cosine is not None and inputs.resume_embedding:
        blended = 0.5 * whole_doc + 0.5 * section_cos
    elif inputs.exp_section_cosine is not None:
        blended = exp_cos_remapped
    elif inputs.section_cosine is not None:
        blended = section_cos
    else:
        blended = whole_doc

    return whole_doc, exp_cos_remapped, blended


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def compute_signals(inputs: ScoreInputs) -> RawSignals:
    """Compute all 6 raw signals. Pure (no I/O, no side effects)."""
    weights = get_weights()

    req_kw, pref_kw, kw = _kw_signal(inputs.jd_text, inputs.resume_text)
    skill_cov, domain_align, skill = _skill_signal(inputs.resume_json, inputs.jd_text)
    ngram = _ngram_signal(inputs.jd_text, inputs.resume_text)
    edu = _edu_signal(inputs.resume_json, inputs.jd_text)
    seniority = _seniority_signal(inputs.resume_json, inputs.jd_text)
    whole_doc_cos, exp_cos, cosine = _cosine_signal(inputs, weights.p_low, weights.p_high)

    raw = (
        kw * weights.w_kw
        + skill * weights.w_skill
        + ngram * weights.w_ngram
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
        edu=edu,
        seniority=seniority,
        whole_doc_cos=whole_doc_cos,
        exp_cos=exp_cos,
        cosine=cosine,
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
) -> dict:
    """Score a resume against a JD. Returns score + breakdown dict.

    Backward-compatible signature — callers that only pass the first 3 args
    still work; new callers can pass exp_section_cosine for a richer signal.
    """
    inputs = ScoreInputs(
        resume_text=resume_text,
        resume_json=resume_json,
        jd_text=jd_text,
        resume_embedding=resume_embedding,
        jd_embedding=jd_embedding,
        section_cosine=section_cosine,
        exp_section_cosine=exp_section_cosine,
        resume_id=resume_id,
    )
    signals = compute_signals(inputs)
    _log_score_event(signals, resume_id, jd_text)

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
    }


# ---------------------------------------------------------------------------
# Score event logging
# ---------------------------------------------------------------------------

_SCORE_LOG_PATH = _Path(__file__).resolve().parents[3] / "data" / "score_log.jsonl"


def _log_score_event(signals: RawSignals, resume_id: Optional[str], jd_text: str) -> None:
    """Best-effort append to score_log.jsonl. Never raises."""
    try:
        _SCORE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        excerpt = (jd_text or "")[:240].replace("\n", " ").strip()
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
            # N-gram signal
            "ngram_raw": round(signals.ngram, 4),
            # Education and seniority
            "edu_raw": round(signals.edu, 4),
            "seniority_raw": round(signals.seniority, 4),
            # Cosine signals
            "whole_doc_cos_raw": round(signals.whole_doc_cos, 4),
            "exp_cos_raw": round(signals.exp_cos, 4),
            "cosine_blended": round(signals.cosine, 4),
            "final_score": signals.final_score,
        }
        with _SCORE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(event) + "\n")
    except Exception as e:
        logger.debug("Score log write failed: %s", e)


# ---------------------------------------------------------------------------
# Legacy diagnostic (kept for UI compatibility)
# ---------------------------------------------------------------------------

def diagnose_score(breakdown: dict, section_scores: dict, ceiling: dict) -> dict:
    """Classify why a score is stuck and suggest a remedy."""
    bm25 = breakdown.get("bm25", 0) / 100.0
    semantic = breakdown.get("semantic", 0) / 100.0
    skill_coverage = breakdown.get("skill_coverage", 0) / 100.0

    w = get_weights()
    score = int(round(
        (bm25 * w.w_kw + skill_coverage * w.w_skill + semantic * w.w_cos
         + 1.0 * w.w_ngram + 1.0 * w.w_edu + 1.0 * w.w_sen) * 100
    ))

    if score >= 75:
        return {"code": "good", "headline": "", "detail": ""}

    exp_required = ceiling.get("exp_required")
    exp_actual = ceiling.get("exp_actual")
    if (
        isinstance(exp_required, int) and exp_required > 0
        and exp_actual is not None
        and exp_actual + 0.5 < exp_required
    ):
        return {
            "code": "experience_gap_years",
            "headline": f"This role requires {exp_required}+ years of experience",
            "detail": (
                f"Your resume shows ~{exp_actual:g} years. "
                "Tailoring keywords and showcasing relevant projects "
                "can still improve your score significantly."
            ),
        }

    if semantic < 0.55 and bm25 < 0.55:
        return {
            "code": "low_coverage",
            "headline": "Low match — your resume needs more JD-relevant keywords",
            "detail": (
                "Your resume doesn't yet cover the key terms this role looks for. "
                "Use the Tailor tab to accept suggestions and generate projects — "
                "each accepted change directly moves your match score."
            ),
        }

    return {
        "code": "low_coverage",
        "headline": f"Score is {score}% — tailoring can push it higher",
        "detail": (
            "Some JD keywords are missing from your resume. "
            "Accept more suggestions or add relevant skills to improve coverage."
        ),
    }
