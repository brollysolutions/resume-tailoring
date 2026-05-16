"""
Hybrid scoring: keyword coverage (55%) + skill JD coverage (25%) + semantic cosine (20%).

CPU-friendly alternative to LLM-based scoring.
Uses ONNX sentence-transformers for fast embeddings on CPU.
"""

import logging
from typing import Optional
from app.core.keyword_utils import _significant_tokens, _fuzzy_coverage, _top_jd_tokens
from app.core.skill_taxonomy import domain_of
from .nlp_utils import keyword_coverage, extract_skills

logger = logging.getLogger(__name__)


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = sum(x * x for x in vec_a) ** 0.5
    mag_b = sum(x * x for x in vec_b) ** 0.5

    if mag_a <= 0 or mag_b <= 0:
        return 0.0

    return dot / (mag_a * mag_b)


def _resume_text_for_skills(resume_json: dict) -> str:
    """Concatenate every place a skill might appear: skills section,
    summary, experience bullets, project bullets, project tech."""
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


def _skill_jd_coverage(resume_json: dict, jd_text: str) -> float:
    """Score: |JD-required skills found in resume| / |JD-required skills|.

    Uses extract_skills (curated _TECH_SKILLS vocabulary) on both sides so
    we don't substring-match "go" inside "google". Direction is JD->resume:
    "did the candidate cover what the role asks for?" — not "are my listed
    skills mentioned anywhere in the JD?".

    Taxonomy expansion (Tier 3): same-domain skills get half credit, so a
    JD asking PostgreSQL with a resume listing MySQL gets 0.5 (both
    database/sql), not 0.

    Returns:
        Score [0, 1]
    """
    jd_skills = extract_skills(jd_text)
    if not jd_skills:
        return 0.0

    resume_skills = extract_skills(_resume_text_for_skills(resume_json))

    matched = jd_skills & resume_skills
    unmatched_jd = jd_skills - matched

    # Half-credit for same-domain matches (e.g. JD wants PostgreSQL,
    # resume has MySQL — both database/sql).
    resume_domains = {d for d in (domain_of(s) for s in resume_skills) if d}
    half_credit = sum(0.5 for s in unmatched_jd if domain_of(s) in resume_domains)

    return min((len(matched) + half_credit) / len(jd_skills), 1.0)


def score_resume_against_jd(
    resume_text: str,
    resume_json: dict,
    jd_text: str,
    resume_embedding: Optional[list[float]] = None,
    jd_embedding: Optional[list[float]] = None,
    section_cosine: Optional[float] = None,
    resume_id: Optional[str] = None,
) -> dict:
    """Hybrid score: keyword (55%) + skill coverage (25%) + cosine semantic (20%).

    Args:
        resume_text: Plaintext resume
        resume_json: Structured Resume model as dict
        jd_text: Job description text
        resume_embedding: Pre-computed resume embedding vector
        jd_embedding: Pre-computed JD embedding vector

    Returns:
        {
            "score": int [0-100],
            "breakdown": {
                "bm25": int [0-100],
                "semantic": int [0-100],
                "skill_coverage": int [0-100],
            }
        }
    """
    # Keyword overlap (55% weight) — uses _top_jd_tokens internally so the
    # scoring token set matches the tailoring orchestrator's injection set.
    bm25_score = keyword_coverage(jd_text, resume_text)

    # Cosine semantic similarity (20% weight). Blends whole-document cosine
    # (global similarity) with per-section max cosine (specific hot-spot).
    # Whole-doc captures overall fit; section-max rewards a strong bullet-to-
    # requirement overlap that whole-doc dilutes.
    whole_doc_cos = 0.0
    if resume_embedding and jd_embedding:
        try:
            raw = _cosine_similarity(resume_embedding, jd_embedding)
            # Remap [0.3, 1.0] -> [0, 1]; unrelated tech docs typically sit at 0.3+.
            whole_doc_cos = max(0.0, (raw - 0.3) / 0.7)
        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")

    section_cos_remapped = 0.0
    if section_cosine is not None:
        section_cos_remapped = max(0.0, (section_cosine - 0.3) / 0.7)

    if section_cosine is not None and (resume_embedding and jd_embedding):
        # Both signals available — blend equally so neither dominates.
        semantic_score = 0.5 * whole_doc_cos + 0.5 * section_cos_remapped
    elif section_cosine is not None:
        semantic_score = section_cos_remapped
    else:
        semantic_score = whole_doc_cos

    # Skill coverage: how many resume skills appear in JD (25% weight)
    skill_score = _skill_jd_coverage(resume_json, jd_text)

    # Weighted combination: keyword 55% + skill 25% + cosine 20%
    raw_score = (bm25_score * 0.55) + (skill_score * 0.25) + (semantic_score * 0.20)
    raw_score = max(0.0, min(1.0, raw_score))

    final_score = int(round(raw_score * 100))

    # Tier 2A: log raw component scores so the offline calibration harness
    # in backend/scripts/calibration/ can grid-search weights against labels.
    _log_score_event(
        jd_text=jd_text,
        kw_raw=bm25_score,
        skill_raw=skill_score,
        whole_doc_cos=whole_doc_cos,
        section_cos=section_cosine,
        cosine_blended=semantic_score,
        final=final_score,
        resume_id=resume_id,
    )

    return {
        "score": final_score,
        "breakdown": {
            "bm25": int(round(bm25_score * 100)),
            "semantic": int(round(semantic_score * 100)),
            "skill_coverage": int(round(skill_score * 100)),
        },
    }


# JSONL log path. Async-safe (single line append, no shared state). Path is
# repo-relative so it works in docker (where backend/data is mounted) and in
# local uvicorn runs.
import json as _json
import hashlib as _hashlib
from datetime import datetime as _datetime, timezone as _timezone
from pathlib import Path as _Path

_SCORE_LOG_PATH = _Path(__file__).resolve().parents[3] / "data" / "score_log.jsonl"


def _log_score_event(
    jd_text: str,
    kw_raw: float,
    skill_raw: float,
    whole_doc_cos: float,
    section_cos: Optional[float],
    cosine_blended: float,
    final: int,
    resume_id: Optional[str] = None,
) -> None:
    """Append one scoring event to score_log.jsonl. Best-effort — never raises.
    `resume_id` and `jd_excerpt` are required by the calibration labeler to
    show the labeler what they are scoring."""
    try:
        _SCORE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        excerpt = (jd_text or "")[:240].replace("\n", " ").strip()
        event = {
            "ts": _datetime.now(_timezone.utc).isoformat(),
            "resume_id": resume_id,
            "jd_hash": _hashlib.sha256(jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16],
            "jd_excerpt": excerpt,
            "kw_raw": round(kw_raw, 4),
            "skill_raw": round(skill_raw, 4),
            "whole_doc_cos_raw": round(whole_doc_cos, 4),
            "section_cos_raw": round(section_cos, 4) if section_cos is not None else None,
            "cosine_blended": round(cosine_blended, 4),
            "final_score": final,
        }
        with _SCORE_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(event) + "\n")
    except Exception as e:
        logger.debug(f"Score log write failed: {e}")


def diagnose_score(breakdown: dict, section_scores: dict, ceiling: dict) -> dict:
    """Classify why a score is stuck and suggest remedy.

    Args:
        breakdown: Hybrid score breakdown dict
        section_scores: Per-section scores dict
        ceiling: Ceiling detection dict

    Returns:
        {
            "code": str,
            "headline": str,
            "detail": str
        }
    """
    bm25 = breakdown.get("bm25", 0) / 100.0
    semantic = breakdown.get("semantic", 0) / 100.0
    skill_coverage = breakdown.get("skill_coverage", 0) / 100.0

    # Calculate composite score from components (same weights as in scorer)
    score = int(round((bm25 * 0.55 + skill_coverage * 0.25 + semantic * 0.20) * 100))

    # Good score
    if score >= 75:
        return {"code": "good", "headline": "", "detail": ""}

    # Years of experience gap
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
                "Expect a lower match percentage — tailoring keywords and showcasing relevant projects "
                "can still improve your score significantly."
            ),
        }

    # Low keyword + semantic coverage — always actionable, never discourage
    if semantic < 55 and bm25 < 55:
        return {
            "code": "low_coverage",
            "headline": f"Low match — your resume needs more JD-relevant keywords",
            "detail": (
                "Your resume doesn't yet cover the key terms this role looks for. "
                "Use the Tailor tab to accept suggestions and generate projects — "
                "each accepted change directly moves your match score."
            ),
        }

    # Partial coverage
    return {
        "code": "low_coverage",
        "headline": f"Score is {score}% — tailoring can push it higher",
        "detail": (
            "Some JD keywords are missing from your resume. "
            "Accept more suggestions or add relevant skills to improve coverage."
        ),
    }
