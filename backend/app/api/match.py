"""
Match endpoints: hybrid scoring with BM25, semantic similarity, and hard requirement ceiling.

Endpoints:
- POST /api/match/: Score resume against JD
- POST /api/match/tailored: Score tailored resume with before/after + section breakdown
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.vector_db import init_qdrant, get_embedding
from app.core.renderer import resume_to_plaintext
from app.models.resume_schema import Resume

from .match_logic import score_resume_against_jd, detect_ceiling, compute_section_scores, parse_jd_hard_requirements, compute_gap_analysis

logger = logging.getLogger(__name__)
router = APIRouter()

_BACKEND = Path(__file__).resolve().parents[2]
_DATA = _BACKEND / "data"
_SECTION_DELTA_PATH = _DATA / "section_deltas.jsonl"


def _log_section_delta(
    resume_id: str,
    jd_hash: str,
    before_sections: dict,
    after_sections: dict,
    score_delta: int,
) -> None:
    """Log section score deltas for per-section calibration analysis. Best-effort."""
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "resume_id": resume_id,
            "jd_hash": jd_hash,
            "before_sections": before_sections or {},
            "after_sections": after_sections or {},
            "score_delta": score_delta,
        }
        with _SECTION_DELTA_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        logger.debug(f"Section delta log write failed: {e}")


class MatchRequest(BaseModel):
    resume_id: str
    jd_text: str


class MatchTailoredRequest(BaseModel):
    resume_id: str
    jd_text: str
    accepted_suggestions: list = []
    new_projects: list = []


@router.post("/")
async def match_resume(req: MatchRequest):
    """Score resume against JD.

    Returns:
    {
        "score": int,
        "breakdown": {
            "bm25": int,
            "semantic": int,
            "skill_coverage": int,
            "heuristic": int
        },
        "section_scores": {...},
        "ceiling": {...},
        "diagnosis": {...}
    }
    """
    # Load resume from Qdrant (with vector for semantic similarity)
    q_client = init_qdrant("resumes")
    results = q_client.retrieve(collection_name="resumes", ids=[req.resume_id], with_payload=True, with_vectors=True)
    if not results:
        raise HTTPException(status_code=404, detail="Resume not found")

    payload = results[0].payload
    resume_json = payload.get("resume_json")
    resume_text = payload.get("text", "")
    resume_vector = results[0].vector if hasattr(results[0], 'vector') and results[0].vector else None

    # Parse resume JSON
    try:
        from app.models.resume_schema import Resume
        resume_obj = Resume.model_validate_json(resume_json)
    except Exception as e:
        logger.exception("Failed to parse resume JSON")
        raise HTTPException(status_code=500, detail=f"Invalid resume JSON: {e}")

    # Embed JD for semantic similarity
    try:
        jd_embedding = await get_embedding(req.jd_text)
    except Exception as e:
        logger.warning(f"JD embedding failed: {e}")
        jd_embedding = None

    # Per-section cosine (per-block max) for backward compat
    section_cosine = None
    try:
        from .match_logic.section_embedder import compute_section_cosine
        section_cosine = await compute_section_cosine(
            resume_obj.model_dump(), req.jd_text, get_embedding
        )
    except Exception as e:
        logger.warning(f"Section cosine failed: {e}")

    # Experience-section cosine (more targeted than per-block max)
    exp_section_cosine = None
    try:
        from .match_logic.section_scorer import compute_experience_cosine
        exp_section_cosine = await compute_experience_cosine(
            resume_obj, jd_embedding, get_embedding
        )
    except Exception as e:
        logger.warning(f"Experience cosine failed: {e}")

    # Hybrid scoring with embeddings
    try:
        result = score_resume_against_jd(
            resume_text, resume_obj.model_dump(), req.jd_text,
            resume_vector, jd_embedding,
            section_cosine=section_cosine,
            exp_section_cosine=exp_section_cosine,
            resume_id=req.resume_id,
        )
    except Exception as e:
        logger.exception("Hybrid scoring failed")
        raise HTTPException(status_code=500, detail=f"Scoring failed: {e}")

    # Hard requirement ceiling — regex extraction, no LLM
    hard_reqs = parse_jd_hard_requirements(req.jd_text)
    ceiling = detect_ceiling(resume_obj, hard_reqs)

    # Log ceiling hits for calibration (Signal 5: hard "bad" label)
    if ceiling and ceiling.get("score", 100) < 40:
        import hashlib
        from app.core.implicit_labeler import log_suggestion_event
        jd_hash = hashlib.sha256(req.jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        log_suggestion_event("ceiling_hit", resume_id=req.resume_id, jd_hash=jd_hash)

    # Per-section scores
    try:
        section_scores = await compute_section_scores(resume_obj, resume_obj.model_dump(), req.jd_text, jd_embedding)
    except Exception as e:
        logger.warning(f"Section scoring failed: {e}")
        section_scores = {}

    # Diagnosis
    from .match_logic.hybrid_scorer import diagnose_score
    diagnosis = diagnose_score(result["breakdown"], section_scores, ceiling)

    # Gap analysis
    try:
        gap_analysis = compute_gap_analysis(resume_obj, resume_text, req.jd_text, section_scores)
    except Exception as e:
        logger.warning(f"Gap analysis failed: {e}")
        gap_analysis = None

    # AI-driven per-section diagnosis (replaces raw missing-keyword chips in UI).
    # Runs only when low_sections is non-empty so high-scoring resumes incur no LLM cost.
    if gap_analysis and gap_analysis.get("low_sections"):
        try:
            from app.core.llm_helpers import analyze_low_sections
            from .match_logic.section_scorer import _section_text
            payload = [
                {
                    "section": s["section"],
                    "score": s["score"],
                    "text": _section_text(resume_obj, s["section"]),
                }
                for s in gap_analysis["low_sections"]
            ]
            explanations = await analyze_low_sections(req.jd_text, payload)
            for s in gap_analysis["low_sections"]:
                s["explanation"] = explanations.get(s["section"], "")
        except Exception as e:
            logger.warning(f"Section diagnosis failed: {e}")

    from app.core.weights_store import get_weights
    w = get_weights()
    return {
        "score": result["score"],
        "breakdown": result["breakdown"],
        "section_scores": section_scores,
        "ceiling": ceiling,
        "diagnosis": diagnosis,
        "gap_analysis": gap_analysis,
        "active_weights": {
            "w_kw": round(w.w_kw * 100),
            "w_skill": round(w.w_skill * 100),
            "w_ngram": round(w.w_ngram * 100),
            "w_edu": round(w.w_edu * 100),
            "w_sen": round(w.w_sen * 100),
            "w_cos": round(w.w_cos * 100),
        },
    }


@router.post("/tailored")
async def match_tailored(req: MatchTailoredRequest):
    """Score resume before and after tailoring suggestions.

    Applies accepted_suggestions to resume, re-scores, returns before/after breakdown.

    Returns:
    {
        "original": { score, breakdown, section_scores, ... },
        "tailored": { score, breakdown, section_scores, ... },
        "delta": int (score improvement)
    }
    """
    # Load resume (with vector for semantic similarity)
    q_client = init_qdrant("resumes")
    results = q_client.retrieve(collection_name="resumes", ids=[req.resume_id], with_payload=True, with_vectors=True)
    if not results:
        raise HTTPException(status_code=404, detail="Resume not found")

    payload = results[0].payload
    resume_json = payload.get("resume_json")

    # Parse resume
    try:
        resume_obj = Resume.model_validate_json(resume_json)
    except Exception as e:
        logger.exception("Failed to parse resume JSON")
        raise HTTPException(status_code=500, detail=f"Invalid resume JSON: {e}")

    resume_text_original = resume_to_plaintext(resume_obj)

    # Embed JD once (reuse for both original and tailored)
    try:
        jd_embedding = await get_embedding(req.jd_text)
    except Exception as e:
        logger.warning(f"JD embedding failed: {e}")
        jd_embedding = None

    # Score original
    try:
        from .match_logic.section_embedder import compute_section_cosine
        original_resume_vector = results[0].vector if hasattr(results[0], 'vector') and results[0].vector else None
        original_section_cos = None
        try:
            original_section_cos = await compute_section_cosine(
                resume_obj.model_dump(), req.jd_text, get_embedding
            )
        except Exception as e:
            logger.warning(f"Original section cosine failed: {e}")
        original_exp_cos = None
        try:
            from .match_logic.section_scorer import compute_experience_cosine
            original_exp_cos = await compute_experience_cosine(resume_obj, jd_embedding, get_embedding)
        except Exception:
            pass
        original_result = score_resume_against_jd(
            resume_text_original, resume_obj.model_dump(), req.jd_text,
            original_resume_vector, jd_embedding,
            section_cosine=original_section_cos,
            exp_section_cosine=original_exp_cos,
            resume_id=req.resume_id,
        )
        original_sections = await compute_section_scores(resume_obj, resume_obj.model_dump(), req.jd_text, jd_embedding)
    except Exception as e:
        logger.exception("Original scoring failed")
        raise HTTPException(status_code=500, detail=f"Scoring failed: {e}")

    # Apply suggestions and re-score
    try:
        from app.core.renderer import apply_suggestions as apply_sugg
        from app.api.tailor import _replace_projects

        resume_tailored = apply_sugg(resume_obj, req.accepted_suggestions)
        if req.new_projects:
            resume_tailored = _replace_projects(resume_tailored, req.new_projects)
        resume_text_tailored = resume_to_plaintext(resume_tailored)

        # Embed tailored resume text for semantic similarity
        try:
            tailored_resume_vector = await get_embedding(resume_text_tailored)
        except Exception as e:
            logger.warning(f"Tailored resume embedding failed: {e}")
            tailored_resume_vector = None

        tailored_section_cos = None
        try:
            tailored_section_cos = await compute_section_cosine(
                resume_tailored.model_dump(), req.jd_text, get_embedding
            )
        except Exception as e:
            logger.warning(f"Tailored section cosine failed: {e}")
        tailored_exp_cos = None
        try:
            from .match_logic.section_scorer import compute_experience_cosine as _cec
            tailored_exp_cos = await _cec(resume_tailored, jd_embedding, get_embedding)
        except Exception:
            pass
        tailored_result = score_resume_against_jd(
            resume_text_tailored, resume_tailored.model_dump(), req.jd_text,
            tailored_resume_vector, jd_embedding,
            section_cosine=tailored_section_cos,
            exp_section_cosine=tailored_exp_cos,
            resume_id=req.resume_id,
        )
        tailored_sections = await compute_section_scores(resume_tailored, resume_tailored.model_dump(), req.jd_text, jd_embedding)
    except Exception as e:
        logger.exception("Tailored scoring failed")
        raise HTTPException(status_code=500, detail=f"Tailored scoring failed: {e}")

    delta = tailored_result["score"] - original_result["score"]

    # Log section deltas for per-section calibration analysis (Signal 6)
    import hashlib
    jd_hash = hashlib.sha256(req.jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
    _log_section_delta(
        resume_id=req.resume_id,
        jd_hash=jd_hash,
        before_sections=original_sections,
        after_sections=tailored_sections,
        score_delta=delta,
    )

    return {
        "original": {
            "score": original_result["score"],
            "breakdown": original_result["breakdown"],
            "section_scores": original_sections,
        },
        "tailored": {
            "score": tailored_result["score"],
            "breakdown": tailored_result["breakdown"],
            "section_scores": tailored_sections,
        },
        "delta": delta,
    }
