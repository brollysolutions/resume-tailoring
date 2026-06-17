"""
Per-section scoring: Match each resume section separately against JD.

Each section uses its own weight blend (calibrated if available, hand-tuned
defaults otherwise) since the global 6-feature formula produces noise floors
when applied to short isolated section text (e.g., seniority defaulting to 0.7
for a Skills section that has no dates).

Returns breakdown by Summary, Experience, Projects, Skills for granular feedback.
Also logs per-section raw signals to section_score_log.jsonl so per-section
weights can be calibrated offline.
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SECTIONS = ("Summary", "Experience", "Projects", "Skills")

# Hand-tuned fallback per-section weights. Each section emphasizes the features
# that actually apply to its content. Sums to 1.0 per section.
# Override via weights_active.json.section_weights once calibration produces
# better numbers (see tune_section_weights.py).
# Narrative sections (experience, projects) emphasize semantic alignment over
# strict JD-wide keyword coverage (which naturally penalizes isolated blocks).
DEFAULT_SECTION_WEIGHTS: dict[str, dict[str, float]] = {
    "summary":    {"w_kw": 0.30, "w_skill": 0.10, "w_ngram": 0.00, "w_edu": 0.00, "w_sen": 0.00, "w_cos": 0.60},
    "experience": {"w_kw": 0.20, "w_skill": 0.05, "w_ngram": 0.05, "w_edu": 0.00, "w_sen": 0.00, "w_cos": 0.70},
    "projects":   {"w_kw": 0.20, "w_skill": 0.05, "w_ngram": 0.05, "w_edu": 0.00, "w_sen": 0.00, "w_cos": 0.70},
    "skills":     {"w_kw": 0.40, "w_skill": 0.55, "w_ngram": 0.00, "w_edu": 0.00, "w_sen": 0.00, "w_cos": 0.05},
}

# R5: Dynamic section-specific remapping bounds. Since isolated sections have
# fewer tokens, their raw cosine with a long JD is naturally lower than a
# full-doc cosine. Using global resume bounds (e.g. 0.18-0.53) crushes section
# scores. We use a lower, wider window for section-doc comparisons.
_SEC_P_LOW = 0.10
_SEC_P_HIGH = 0.35

_BACKEND = Path(__file__).resolve().parents[3]
_SECTION_LOG_PATH = _BACKEND / "data" / "section_score_log.jsonl"


def _section_text(resume, section: str) -> str:
    """Extract plaintext for one resume section.

    Args:
        resume: Resume object
        section: Section name (Summary, Experience, Projects, Skills)

    Returns:
        Plaintext for that section, or empty string if missing.
    """
    section = section.lower()
    lines: list[str] = []

    if section == "summary":
        if resume.summary:
            lines.append(resume.summary)

    elif section == "experience":
        for e in resume.experience:
            head = f"{e.title} @ {e.company}"
            if e.location:
                head += f" ({e.location})"
            lines.append(head)
            lines.extend(e.bullets or [])

    elif section == "projects":
        for p in resume.projects:
            head = p.name + (f" — {p.tech}" if p.tech else "")
            lines.append(head)
            lines.extend(p.bullets or [])

    elif section == "skills":
        for sk in resume.skills:
            if sk.category and sk.category.lower() != "skills":
                lines.append(f"{sk.category}: {', '.join(sk.skills or [])}")
            else:
                lines.append(f"{', '.join(sk.skills or [])}")

    return "\n".join(filter(None, lines))


def _resolve_section_weights(section_name: str) -> dict:
    """Look up calibrated weights for this section, fall back to defaults."""
    from app.core.weights_store import get_section_weights
    sw = get_section_weights(section_name)
    if sw and all(k in sw for k in ("w_kw", "w_skill", "w_ngram", "w_edu", "w_sen", "w_cos")):
        return {k: float(sw[k]) for k in ("w_kw", "w_skill", "w_ngram", "w_edu", "w_sen", "w_cos")}
    return dict(DEFAULT_SECTION_WEIGHTS[section_name.lower()])


def _log_section_event(
    resume_id: Optional[str],
    jd_text: str,
    section_name: str,
    result: dict,
) -> None:
    """Append per-section raw signals to section_score_log.jsonl.

    Best-effort: never raises. Used by tune_section_weights.py offline calibrator.
    """
    if os.environ.get("TESTING") == "1":
        return
    if not resume_id:
        return
    try:
        _SECTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        bd = result.get("breakdown") or {}
        fc = result.get("feature_contributions") or {}
        # R4: ngram_active travels via the result dict. Default True for any
        # legacy caller that doesn't set it (preserves pre-R4 behavior).
        ngram_active = bool(result.get("ngram_active", True))
        ngram_cov = fc.get("ngram", 0) / 100.0
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "resume_id": resume_id,
            "jd_hash": hashlib.sha256(jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16],
            "section": section_name.lower(),
            # Raw signal contributions (0-100 ints) — same shape per section so
            # tune_section_weights can grid-search uniformly.
            "kw_raw": fc.get("keyword", 0) / 100.0,
            "skill_raw": (bd.get("skill_coverage", 0)) / 100.0,
            # Legacy 1.0-sentinel-when-inactive (R4 back-compat).
            "ngram_raw": (1.0 if not ngram_active else ngram_cov),
            "ngram_coverage": ngram_cov,
            "ngram_active": ngram_active,
            "edu_raw": fc.get("edu", 100) / 100.0,
            "seniority_raw": fc.get("seniority", 70) / 100.0,
            "cosine_blended": fc.get("cosine", 0) / 100.0,
            "section_score": result.get("score", 0),
        }
        with _SECTION_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        logger.debug("section_score_log write failed: %s", e)


async def compute_section_scores(
    resume,
    resume_json: dict,
    jd_text: str,
    jd_embedding: Optional[list[float]] = None,
    resume_id: Optional[str] = None,
) -> dict:
    """Score each non-empty resume section against JD independently using
    per-section weight presets (calibrated or hand-tuned defaults).

    Returns:
        {
            "Summary": {"score": int, "features": {...}, "weights_used": {...}} | None,
            "Experience": ...,
            "Projects": ...,
            "Skills": ...,
        }
    """
    from .hybrid_scorer import score_resume_against_jd
    from app.core.vector_db import get_embedding

    texts = {s: _section_text(resume, s) for s in _SECTIONS}
    non_empty = [(s, t) for s, t in texts.items() if t.strip()]

    if not non_empty:
        return {s: None for s in _SECTIONS}

    # Embed JD once; embed each section in parallel
    try:
        embed_tasks = [get_embedding(t) for _, t in non_empty]
        if jd_embedding is None:
            embed_tasks.append(get_embedding(jd_text))
        results_emb = await asyncio.gather(*embed_tasks, return_exceptions=True)

        section_embeddings = {}
        for i, (section, _) in enumerate(non_empty):
            emb = results_emb[i]
            section_embeddings[section] = emb if isinstance(emb, list) else None

        if jd_embedding is None:
            raw_jd = results_emb[-1]
            jd_embedding = raw_jd if isinstance(raw_jd, list) else None
    except Exception as e:
        logger.warning(f"Section embedding failed: {e}")
        section_embeddings = {s: None for s, _ in non_empty}

    out: dict = {s: None for s in _SECTIONS}

    for section, text in non_empty:
        if section == "Skills":
            section_json = {"skills": resume_json.get("skills", [])}
        elif section == "Experience":
            section_json = {"experience": resume_json.get("experience", [])}
        elif section == "Projects":
            section_json = {"projects": resume_json.get("projects", [])}
        elif section == "Summary":
            section_json = {"summary": resume_json.get("summary", "")}
        else:
            section_json = {}

        weights_override = _resolve_section_weights(section)

        result = await score_resume_against_jd(
            text, section_json, jd_text,
            resume_embedding=section_embeddings.get(section),
            jd_embedding=jd_embedding,
            weights_override=weights_override,
            log_event=False,  # per-section uses section_score_log instead
            resume_id=resume_id,
            resume_obj=None,
            p_low_override=_SEC_P_LOW,
            p_high_override=_SEC_P_HIGH,
        )

        _log_section_event(resume_id, jd_text, section, result)

        out[section] = {
            "score": result["score"],
            "features": result.get("feature_contributions", {}),
            "weights_used": result.get("weights_used", {}),
        }

    return out


async def compute_experience_cosine(
    resume_obj,
    jd_embedding: Optional[list[float]],
    get_embedding_fn,
) -> Optional[float]:
    """Raw cosine between the experience section embedding and JD embedding.

    Returns None when experience section is empty or embeddings fail.
    The raw (pre-remap) value is returned — hybrid_scorer remaps it.
    """
    if not jd_embedding:
        return None
    try:
        exp_text = _section_text(resume_obj, "Experience")
        if not exp_text.strip():
            return None
        exp_emb = await get_embedding_fn(exp_text)
        if not exp_emb:
            return None
        from app.api.match_logic.hybrid_scorer import _cosine_similarity
        return _cosine_similarity(exp_emb, jd_embedding)
    except Exception as e:
        logger.warning("compute_experience_cosine failed: %s", e)
        return None


async def compute_section_cosines(
    resume_obj,
    jd_embedding: Optional[list[float]],
    get_embedding_fn,
) -> dict:
    """Raw pre-remap cosines per section (R5 section-weighted cosine).

    Returns {section: cosine} only for sections with non-empty text.
    Caller passes this dict to score_resume_against_jd which computes
    the weighted average using _SECTION_COS_WEIGHTS in hybrid_scorer.
    """
    if not jd_embedding:
        return {}
    result: dict = {}
    for section in _SECTIONS:
        text = _section_text(resume_obj, section)
        if not text.strip():
            continue
        try:
            emb = await get_embedding_fn(text)
            if emb:
                from app.api.match_logic.hybrid_scorer import _cosine_similarity
                result[section] = _cosine_similarity(emb, jd_embedding)
        except Exception as e:
            logger.warning("compute_section_cosines %s failed: %s", section, e)
    return result
