"""
Match endpoints: hybrid scoring with BM25, semantic similarity, and hard requirement ceiling.

Endpoints:
- POST /api/match/: Score resume against JD
- POST /api/match/tailored: Score tailored resume with before/after + section breakdown
"""

import asyncio
import json
import logging
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.vector_db import init_qdrant, get_embedding, get_embeddings
from app.core.renderer import resume_to_plaintext
from app.core.keyword_utils import _significant_tokens
from app.core.cache import get_cached_value, set_cached_value
from app.models.resume_schema import Resume

from .match_logic import score_resume_against_jd, detect_ceiling, compute_section_scores, parse_jd_hard_requirements, compute_gap_analysis, build_improvement_plan

logger = logging.getLogger(__name__)
router = APIRouter()

# In-process cache for invariant original snapshots
# Key: (resume_id, jd_hash)
# Value: dict of {score, breakdown, section_scores}
_ORIGINAL_SNAPSHOT_CACHE: dict[tuple[str, str], dict] = {}
_MAX_SNAPSHOT_CACHE_SIZE = 100

def _get_cached_original_snapshot(resume_id: str, jd_text: str) -> Optional[dict]:
    """Retrieve original snapshot from the in-process cache."""
    jd_hash = hashlib.sha256(jd_text.encode("utf-8", errors="ignore")).hexdigest()
    key = (resume_id, jd_hash)
    val = _ORIGINAL_SNAPSHOT_CACHE.get(key)
    if val:
        logger.info(f"[CACHE] hit for original snapshot for resume_id={resume_id}")
    return val

def _set_cached_original_snapshot(resume_id: str, jd_text: str, snapshot: dict) -> None:
    """Store original snapshot in the in-process cache."""
    jd_hash = hashlib.sha256(jd_text.encode("utf-8", errors="ignore")).hexdigest()
    key = (resume_id, jd_hash)
    if len(_ORIGINAL_SNAPSHOT_CACHE) >= _MAX_SNAPSHOT_CACHE_SIZE:
        try:
            oldest_key = next(iter(_ORIGINAL_SNAPSHOT_CACHE))
            _ORIGINAL_SNAPSHOT_CACHE.pop(oldest_key)
        except StopIteration:
            pass
    _ORIGINAL_SNAPSHOT_CACHE[key] = snapshot


async def _prewarm_embeddings(resume_obj, resume_json: dict, jd_text: str, full_text: Optional[str] = None) -> None:
    """
    Collect all texts that will be embedded during the scoring process
    and call get_embeddings in a single batched pass to prewarm the cache.
    """
    from app.api.match_logic.section_embedder import extract_jd_requirements, resume_content_blocks
    from app.api.match_logic.section_scorer import _section_text, _SECTIONS

    texts_to_embed = []

    # 1. Job Description text
    if jd_text and jd_text.strip():
        texts_to_embed.append(jd_text)

    # 2. JD Requirements
    jd_reqs = extract_jd_requirements(jd_text)
    if jd_reqs and jd_reqs.strip():
        texts_to_embed.append(jd_reqs)

    # 3. Resume Content Blocks
    blocks = resume_content_blocks(resume_json)
    for block in blocks:
        if block and block.strip():
            texts_to_embed.append(block)

    # 4. Per-section texts
    for section in _SECTIONS:
        sec_text = _section_text(resume_obj, section)
        if sec_text and sec_text.strip():
            texts_to_embed.append(sec_text)

    # 5. Full text (tailored whole-doc plaintext) if provided
    if full_text and full_text.strip():
        texts_to_embed.append(full_text)

    # Deduplicate and call get_embeddings
    if texts_to_embed:
        try:
            logger.info(f"[TIMING] Prewarming {len(texts_to_embed)} embeddings in a batch")
            start_time = datetime.now()
            await get_embeddings(texts_to_embed)
            elapsed = (datetime.now() - start_time).total_seconds() * 1000.0
            logger.info(f"[TIMING] Prewarmed {len(texts_to_embed)} embeddings in {elapsed:.2f}ms")
        except Exception as e:
            logger.warning(f"Embedding prewarming failed: {e}")


def _get_tailored_cache_key(req: "MatchTailoredRequest") -> str:
    """Deterministic key for caching tailored match results."""
    # Convert lists/dicts to stable strings for hashing
    sugg_str = json.dumps(req.accepted_suggestions, sort_keys=True)
    proj_str = json.dumps(req.new_projects, sort_keys=True)
    raw = f"{req.resume_id}|{req.jd_text}|{sugg_str}|{proj_str}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


_BACKEND = Path(__file__).resolve().parents[2]
_DATA = _BACKEND / "data"
_SECTION_DELTA_PATH = _DATA / "section_deltas.jsonl"

_MIN_JD_CHARS = 200
_MIN_JD_TOKENS = 30


def _validate_jd(jd_text: str) -> None:
    """Reject JDs too short to score meaningfully.

    Threshold tuned to catch placeholder inputs like 'This is my job description'
    (28 chars, 4 tokens) without blocking legitimate brief JDs.
    """
    text = (jd_text or "").strip()
    if len(text) < _MIN_JD_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Job description too short ({len(text)} chars). Paste at least {_MIN_JD_CHARS} characters of the actual JD so we can score it accurately.",
        )
    tokens = _significant_tokens(text)
    if len(tokens) < _MIN_JD_TOKENS:
        raise HTTPException(
            status_code=400,
            detail=f"Job description has too few meaningful keywords ({len(tokens)} found). Make sure you pasted the full role description, not just a heading.",
        )


def _log_section_delta(
    resume_id: str,
    jd_hash: str,
    before_sections: dict,
    after_sections: dict,
    score_delta: int,
) -> None:
    """Log section score deltas for per-section calibration analysis. Best-effort."""
    if os.environ.get("TESTING") == "1":
        return
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
    _validate_jd(req.jd_text)

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

    # Prewarm embeddings
    await _prewarm_embeddings(resume_obj, resume_obj.model_dump(), req.jd_text)

    # Embed JD for semantic similarity
    try:
        jd_embedding = await get_embedding(req.jd_text)
    except Exception as e:
        logger.warning(f"JD embedding failed: {e}")
        jd_embedding = None

    # Parallelize all three independent cosine computations
    from .match_logic.section_embedder import compute_section_cosine
    from .match_logic.section_scorer import compute_experience_cosine, compute_section_cosines

    _cos_results = await asyncio.gather(
        compute_section_cosine(resume_obj.model_dump(), req.jd_text, get_embedding),
        compute_experience_cosine(resume_obj, jd_embedding, get_embedding),
        compute_section_cosines(resume_obj, jd_embedding, get_embedding),
        return_exceptions=True,
    )
    section_cosine = _cos_results[0] if not isinstance(_cos_results[0], Exception) else None
    exp_section_cosine = _cos_results[1] if not isinstance(_cos_results[1], Exception) else None
    section_cosines = _cos_results[2] if not isinstance(_cos_results[2], Exception) else {}
    if isinstance(_cos_results[0], Exception):
        logger.warning(f"Section cosine failed: {_cos_results[0]}")
    if isinstance(_cos_results[1], Exception):
        logger.warning(f"Experience cosine failed: {_cos_results[1]}")
    if isinstance(_cos_results[2], Exception):
        logger.warning(f"Section cosines (R5) failed: {_cos_results[2]}")

    # Hard requirement ceiling — regex extraction, no LLM. Computed up-front
    # so the runtime extraction and ceiling decision can be persisted with
    # the score event (R2 — calibration auditing).
    hard_reqs = parse_jd_hard_requirements(req.jd_text)
    ceiling = detect_ceiling(resume_obj, hard_reqs)

    # Hybrid scoring with embeddings
    try:
        result = await score_resume_against_jd(
            resume_text, resume_obj.model_dump(), req.jd_text,
            resume_vector, jd_embedding,
            section_cosine=section_cosine,
            exp_section_cosine=exp_section_cosine,
            resume_id=req.resume_id,
            ceiling=ceiling,
            hard_reqs=hard_reqs,
            section_cosines=section_cosines or None,
            resume_obj=resume_obj,
        )
    except Exception as e:
        logger.exception("Hybrid scoring failed")
        raise HTTPException(status_code=500, detail=f"Scoring failed: {e}")

    # Log ceiling hits for calibration (Signal 5: hard "bad" label)
    if ceiling and ceiling.get("score", 100) < 40:
        import hashlib
        from app.core.implicit_labeler import log_suggestion_event
        jd_hash = hashlib.sha256(req.jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
        log_suggestion_event("ceiling_hit", resume_id=req.resume_id, jd_hash=jd_hash)

    # Per-section scores — now returns {section: {score, features, weights_used}}
    try:
        section_data = await compute_section_scores(
            resume_obj, resume_obj.model_dump(), req.jd_text, jd_embedding,
            resume_id=req.resume_id,
        )
    except Exception as e:
        logger.warning(f"Section scoring failed: {e}")
        section_data = {}

    # Flatten for back-compat: section_scores is still {section: int|None}
    section_scores = {s: (v["score"] if v else None) for s, v in section_data.items()}
    # New: per-section feature contributions for UI breakdown
    section_features = {s: (v["features"] if v else None) for s, v in section_data.items()}

    # Gap analysis
    from .match_logic.gap_analyzer import compute_gap_analysis
    try:
        gap_analysis = compute_gap_analysis(resume_obj, resume_text, req.jd_text, section_scores)
    except Exception as e:
        logger.warning(f"Gap analysis failed: {e}")
        gap_analysis = None

    # AI-driven per-section diagnosis and overall match analysis.
    # We run both concurrently if low_sections exist, or just overall otherwise.
    explanations = {}
    overall_analysis = {
        "diagnosis": {
            "headline": "Match Complete",
            "detail": f"Resume evaluated with a score of {result['score']}.",
            "theme": "info"
        },
        "suggestions": []
    }
    
    from app.core.llm_helpers import analyze_low_sections, analyze_overall_match
    
    tasks = []
    has_low_sections = gap_analysis and gap_analysis.get("low_sections")
    
    if has_low_sections:
        from .match_logic.section_scorer import _section_text
        payload = [
            {
                "section": s["section"],
                "score": s["score"],
                "text": _section_text(resume_obj, s["section"]),
            }
            for s in gap_analysis["low_sections"]
        ]
        tasks.append(analyze_low_sections(
            req.jd_text,
            payload,
            section_gaps=gap_analysis.get("section_gaps"),
        ))
    else:
        # Dummy task to maintain indexing
        tasks.append(asyncio.sleep(0))
        
    tasks.append(analyze_overall_match(req.jd_text, resume_text, result["score"]))
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        if has_low_sections and not isinstance(results[0], Exception):
            explanations = results[0]
        if not isinstance(results[1], Exception):
            overall_analysis = results[1]
            
        if has_low_sections:
            for s in gap_analysis["low_sections"]:
                s["explanation"] = explanations.get(s["section"], "")
    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}")

    from app.core.weights_store import get_weights
    w = get_weights()
    return {
        "score": result["score"],
        "breakdown": result["breakdown"],
        "section_scores": section_scores,
        "section_features": section_features,
        "ceiling": ceiling,
        "diagnosis": overall_analysis.get("diagnosis"),
        "overall_suggestions": overall_analysis.get("suggestions", []),
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
    Cached by input parameters to speed up page reloads.

    Returns:
    {
        "original": { score, breakdown, section_scores, ... },
        "tailored": { score, breakdown, section_scores, ... },
        "delta": int (score improvement)
    }
    """
    _validate_jd(req.jd_text)

    # Check cache
    cache_key = f"tailored_match_v3:{_get_tailored_cache_key(req)}"
    cached = await get_cached_value(cache_key)
    if cached:
        logger.info(f"match_tailored: cache hit for resume_id={req.resume_id}")
        return cached

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

    # Hard requirement ceiling — extract JD requirements once (JD does not
    # change between original/tailored); compute per-snapshot ceiling for
    # logging (R2).
    hard_reqs = parse_jd_hard_requirements(req.jd_text)

    # Embed JD once (reuse for both original and tailored)
    try:
        jd_embedding = await get_embedding(req.jd_text)
    except Exception as e:
        logger.warning(f"JD embedding failed: {e}")
        jd_embedding = None

    # Try to load cached original snapshot
    original_snapshot = _get_cached_original_snapshot(req.resume_id, req.jd_text)

    if original_snapshot is None:
        logger.info(f"[CACHE] Miss for original snapshot. Computing...")
        # Prewarm original embeddings
        await _prewarm_embeddings(resume_obj, resume_obj.model_dump(), req.jd_text)

        original_ceiling = detect_ceiling(resume_obj, hard_reqs)

        # Score original
        try:
            from .match_logic.section_embedder import compute_section_cosine
            original_resume_vector = results[0].vector if hasattr(results[0], 'vector') and results[0].vector else None
            from .match_logic.section_scorer import compute_experience_cosine as _cec_orig, compute_section_cosines as _csc_orig
            _orig_cos = await asyncio.gather(
                compute_section_cosine(resume_obj.model_dump(), req.jd_text, get_embedding),
                _cec_orig(resume_obj, jd_embedding, get_embedding),
                _csc_orig(resume_obj, jd_embedding, get_embedding),
                return_exceptions=True,
            )
            original_section_cos = _orig_cos[0] if not isinstance(_orig_cos[0], Exception) else None
            original_exp_cos = _orig_cos[1] if not isinstance(_orig_cos[1], Exception) else None
            original_section_cosines = _orig_cos[2] if not isinstance(_orig_cos[2], Exception) else {}
            original_result = await score_resume_against_jd(
                resume_text_original, resume_obj.model_dump(), req.jd_text,
                original_resume_vector, jd_embedding,
                section_cosine=original_section_cos,
                exp_section_cosine=original_exp_cos,
                resume_id=req.resume_id,
                ceiling=original_ceiling,
                hard_reqs=hard_reqs,
                section_cosines=original_section_cosines or None,
                resume_obj=resume_obj,
            )
            original_sections_raw = await compute_section_scores(
                resume_obj, resume_obj.model_dump(), req.jd_text, jd_embedding,
                resume_id=req.resume_id,
            )
            original_sections = {s: (v["score"] if v else None) for s, v in original_sections_raw.items()}
        except Exception as e:
            logger.exception("Original scoring failed")
            raise HTTPException(status_code=500, detail=f"Scoring failed: {e}")

        original_snapshot = {
            "score": original_result["score"],
            "breakdown": original_result["breakdown"],
            "section_scores": original_sections,
        }
        _set_cached_original_snapshot(req.resume_id, req.jd_text, original_snapshot)
    else:
        logger.info(f"[CACHE] Hit! Reusing cached original snapshot for resume_id={req.resume_id}")

    # Apply suggestions and re-score
    try:
        from app.core.renderer import apply_suggestions as apply_sugg
        from app.api.tailor import _replace_projects

        resume_tailored = apply_sugg(resume_obj, req.accepted_suggestions)
        if req.new_projects:
            resume_tailored = _replace_projects(resume_tailored, req.new_projects)
        resume_text_tailored = resume_to_plaintext(resume_tailored)
        tailored_ceiling = detect_ceiling(resume_tailored, hard_reqs)

        # Prewarm tailored embeddings
        await _prewarm_embeddings(resume_tailored, resume_tailored.model_dump(), req.jd_text, full_text=resume_text_tailored)

        # Embed tailored resume text for semantic similarity
        try:
            tailored_resume_vector = await get_embedding(resume_text_tailored)
        except Exception as e:
            logger.warning(f"Tailored resume embedding failed: {e}")
            tailored_resume_vector = None

        from .match_logic.section_embedder import compute_section_cosine
        from .match_logic.section_scorer import compute_experience_cosine as _cec, compute_section_cosines as _csc
        _tail_cos = await asyncio.gather(
            compute_section_cosine(resume_tailored.model_dump(), req.jd_text, get_embedding),
            _cec(resume_tailored, jd_embedding, get_embedding),
            _csc(resume_tailored, jd_embedding, get_embedding),
            return_exceptions=True,
        )
        tailored_section_cos = _tail_cos[0] if not isinstance(_tail_cos[0], Exception) else None
        if isinstance(_tail_cos[0], Exception):
            logger.warning(f"Tailored section cosine failed: {_tail_cos[0]}")
        tailored_exp_cos = _tail_cos[1] if not isinstance(_tail_cos[1], Exception) else None
        tailored_section_cosines = _tail_cos[2] if not isinstance(_tail_cos[2], Exception) else {}
        tailored_result = await score_resume_against_jd(
            resume_text_tailored, resume_tailored.model_dump(), req.jd_text,
            tailored_resume_vector, jd_embedding,
            section_cosine=tailored_section_cos,
            exp_section_cosine=tailored_exp_cos,
            resume_id=req.resume_id,
            ceiling=tailored_ceiling,
            hard_reqs=hard_reqs,
            section_cosines=tailored_section_cosines or None,
            resume_obj=resume_tailored,
        )
        tailored_sections_raw = await compute_section_scores(
            resume_tailored, resume_tailored.model_dump(), req.jd_text, jd_embedding,
            resume_id=req.resume_id,
        )
        tailored_sections = {s: (v["score"] if v else None) for s, v in tailored_sections_raw.items()}
    except Exception as e:
        logger.exception("Tailored scoring failed")
        raise HTTPException(status_code=500, detail=f"Tailored scoring failed: {e}")

    delta = tailored_result["score"] - original_snapshot["score"]

    # Improvement plan: ranked "how to improve" actions on the tailored snapshot
    # (deterministic, no LLM) so the list shrinks as the user accepts edits.
    improvement_plan = None
    try:
        from app.core.weights_store import get_weights
        tailored_gap = compute_gap_analysis(
            resume_tailored, resume_text_tailored, req.jd_text, tailored_sections
        )
        improvement_plan = build_improvement_plan(
            req.jd_text,
            tailored_sections,
            tailored_result["score"],
            tailored_ceiling,
            tailored_gap,
            get_weights(),
        )
    except Exception as e:
        logger.warning(f"Improvement plan failed: {e}")

    # Log section deltas for per-section calibration analysis (Signal 6)
    import hashlib
    jd_hash = hashlib.sha256(req.jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
    _log_section_delta(
        resume_id=req.resume_id,
        jd_hash=jd_hash,
        before_sections=original_snapshot["section_scores"],
        after_sections=tailored_sections,
        score_delta=delta,
    )

    result = {
        "original": {
            "score": original_snapshot["score"],
            "breakdown": original_snapshot["breakdown"],
            "section_scores": original_snapshot["section_scores"],
        },
        "tailored": {
            "score": tailored_result["score"],
            "breakdown": tailored_result["breakdown"],
            "section_scores": tailored_sections,
            "ceiling": tailored_ceiling,
            "improvement_plan": improvement_plan,
        },
        "delta": delta,
    }

    # Save to cache (24h TTL)
    await set_cached_value(cache_key, result, ttl=86400)

    return result


class MatchFeedbackRequest(BaseModel):
    resume_id: str
    jd_text: str
    helpful: bool


@router.post("/feedback")
async def match_feedback(req: MatchFeedbackRequest):
    """Record explicit user feedback (thumbs up/down) on match accuracy.

    Writes a source:"human" label to labels.jsonl. Deduped per (resume_id,
    jd_hash) — repeat submits for the same pair return the existing label
    without overwriting.
    """
    jd_hash = hashlib.sha256(req.jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
    label = "good" if req.helpful else "bad"
    from app.core.implicit_labeler import log_human_feedback
    result = log_human_feedback(resume_id=req.resume_id, jd_hash=jd_hash, label=label)
    return result


class MatchGuidanceRequest(MatchTailoredRequest):
    # Tailored per-section scores from the client (already computed by
    # /tailored) so this endpoint needs no embeddings.
    section_scores: Optional[dict] = None


@router.post("/guidance")
async def match_guidance(req: MatchGuidanceRequest):
    """Prompt-driven 'how to improve' guidance for the tailor page.

    Returns plain-English per-section coaching (reusing the job-search section
    diagnosis prompt) plus edge-case coaching for hard-requirement blockers
    (seniority / experience / education). LLM-backed but cheap: no embeddings,
    cached, and each LLM call is skipped when its input is empty.

    {"sections": {section: prose}, "blockers": [{kind, headline, detail}]}
    """
    _validate_jd(req.jd_text)

    cache_key = f"guidance:{_get_tailored_cache_key(req)}"
    cached = await get_cached_value(cache_key)
    if cached:
        logger.info(f"match_guidance: cache hit for resume_id={req.resume_id}")
        return cached

    q_client = init_qdrant("resumes")
    results = q_client.retrieve(collection_name="resumes", ids=[req.resume_id], with_payload=True)
    if not results:
        raise HTTPException(status_code=404, detail="Resume not found")

    try:
        resume_obj = Resume.model_validate_json(results[0].payload.get("resume_json"))
    except Exception as e:
        logger.exception("Failed to parse resume JSON")
        raise HTTPException(status_code=500, detail=f"Invalid resume JSON: {e}")

    # Apply tailoring on the JSON model — no embeddings needed for guidance.
    from app.core.renderer import apply_suggestions as apply_sugg
    from app.api.tailor import _replace_projects
    resume_tailored = apply_sugg(resume_obj, req.accepted_suggestions)
    if req.new_projects:
        resume_tailored = _replace_projects(resume_tailored, req.new_projects)
    resume_text = resume_to_plaintext(resume_tailored)

    section_scores = req.section_scores or {}
    try:
        gap_analysis = compute_gap_analysis(resume_tailored, resume_text, req.jd_text, section_scores)
    except Exception as e:
        logger.warning(f"Guidance gap analysis failed: {e}")
        gap_analysis = {"section_gaps": {}, "low_sections": [], "missing_keywords": []}

    ceiling = detect_ceiling(resume_tailored, parse_jd_hard_requirements(req.jd_text))

    # Low sections (<65) already filtered by compute_gap_analysis using the
    # client-supplied section_scores; attach each section's plaintext.
    from .match_logic.section_scorer import _section_text
    low_payload = [
        {"section": s["section"], "score": s["score"], "text": _section_text(resume_tailored, s["section"])}
        for s in gap_analysis.get("low_sections", [])
    ]

    # Both helpers short-circuit (return {} / []) with NO LLM call when their
    # input is empty, so a strong tailored resume costs nothing here.
    from app.core.llm_helpers import analyze_low_sections, explain_match_blockers
    sections, blockers = await asyncio.gather(
        analyze_low_sections(req.jd_text, low_payload, gap_analysis.get("section_gaps")),
        explain_match_blockers(req.jd_text, ceiling),
        return_exceptions=True,
    )
    if isinstance(sections, Exception):
        logger.warning(f"Section diagnosis failed: {sections}")
        sections = {}
    if isinstance(blockers, Exception):
        logger.warning(f"Blocker explanation failed: {blockers}")
        blockers = []

    result = {"sections": sections or {}, "blockers": blockers or []}
    await set_cached_value(cache_key, result, ttl=86400)
    return result
