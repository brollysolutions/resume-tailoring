"""repro — reproduce the "tailoring lowers the match score" inversion.

Read-only diagnostic. Scores a base resume against an ADK/AI-agent JD, applies a
representative set of accepted tailoring edits (skill adds + experience bullets
that inject JD keywords), then re-scores. Prints the per-signal
feature_contributions before/after so the falling signal is obvious, plus a sweep
of the cosine remap so the p_low cliff is visible.

It reuses the real scorer (`score_resume_against_jd`) and the real applier
(`apply_suggestions`) and the live active weights — nothing is mocked except,
when the embedding model is unavailable, the raw cosine (clearly labelled).

Usage (from repo root or backend/):
    python backend/scripts/audit/repro_tailor_inversion.py
    python -m backend.scripts.audit.repro_tailor_inversion
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `app.*` importable whether run as a module or a file.
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.sample_resume import build_sample_resume
from app.core.renderer import resume_to_plaintext
from app.core.suggestion_applier import apply_suggestions
from app.core.weights_store import get_weights
from app.api.match_logic.hybrid_scorer import score_resume_against_jd

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

JD_TEXT = """
Senior AI Engineer — Agentic Systems

We are building cloud-based AI services and need an engineer fluent in the
Google ADK (Agent Development Kit) to design and ship LLM-powered agents.

Required:
- 2+ years of experience building production AI systems
- Strong Python and FastAPI for API development
- Hands-on experience with LLM applications and RAG (retrieval augmented generation)
- Experience designing AI agents and multi-agent workflows with Google ADK
- Deploying services to cloud (GCP) and integrating vector databases

Preferred:
- Experience with prompt engineering and agent orchestration
- Familiarity with embeddings and semantic search
"""

# Cumulative tailoring batches. The user's regime: a resume that ALREADY matches
# well (kw/skill near max), then more edits get accepted. Once keyword/skill are
# saturated they cannot rise further, so each later batch only adds length ->
# dilutes the embedding -> drops cosine -> score INVERTS. We apply these batches
# cumulatively and score after each to trace the rise-then-fall curve.
#
# All use reliable, non-fuzzy apply paths (add_skill / add_line) so the demo is
# not confounded by the separate fuzzy-match silent-drop bug.
BATCHES: list[tuple[str, list]] = [
    ("1. inject JD skills (adk/llm/rag/fastapi/agents)", [
        {"section": "Skills", "mode": "add_skill", "skill": "ADK", "target_category": "AI & ML", "is_new_category": True},
        {"section": "Skills", "mode": "add_skill", "skill": "LLM", "category": "AI & ML"},
        {"section": "Skills", "mode": "add_skill", "skill": "RAG", "category": "AI & ML"},
        {"section": "Skills", "mode": "add_skill", "skill": "FastAPI", "category": "AI & ML"},
        {"section": "Skills", "mode": "add_skill", "skill": "AI Agents", "category": "AI & ML"},
    ]),
    ("2. inject JD-keyword experience bullets", [
        {"section": "Experience", "mode": "add_line", "original": "experience::0",
         "suggested": "Built LLM-powered AI agents with Google ADK, serving RAG pipelines via FastAPI on GCP."},
        {"section": "Experience", "mode": "add_line", "original": "experience::0",
         "suggested": "Designed multi-agent workflows and integrated vector databases for semantic search."},
    ]),
    ("3. add MORE bullets (keywords already covered)", [
        {"section": "Experience", "mode": "add_line", "original": "experience::0",
         "suggested": "Implemented prompt engineering strategies and agent orchestration for the ADK platform."},
        {"section": "Experience", "mode": "add_line", "original": "experience::0",
         "suggested": "Tuned embeddings and semantic search to improve RAG retrieval quality on GCP."},
    ]),
    ("4. keep tailoring — generic polish bullets", [
        {"section": "Experience", "mode": "add_line", "original": "experience::0",
         "suggested": "Collaborated with cross-functional stakeholders to deliver high-quality outcomes on schedule."},
        {"section": "Experience", "mode": "add_line", "original": "experience::0",
         "suggested": "Owned end-to-end delivery, mentored teammates, and drove continuous process improvements."},
        {"section": "Projects", "mode": "add_line", "original": "projects::0",
         "suggested": "Documented architecture decisions and presented results to leadership for buy-in."},
    ]),
    # Replace-path edits: aggressive verbose rewrites of the original concise
    # bullets. Keywords are already saturated, so these add no kw headroom but
    # make the section embedding more diffuse -> section cosine DROPS -> score
    # erodes. This is the user's regime: "as I tailor, it goes down."
    ("5. aggressive verbose rewrites (replace mode)", [
        {"section": "Experience", "mode": "replace",
         "original": "Built REST APIs serving 2M+ requests per day with sub-100ms p95 latency.",
         "suggested": "Leveraged a broad spectrum of modern engineering practices and cross-functional collaboration to architect, deliver, and continuously improve a wide variety of impactful, high-quality, scalable backend services in a fast-paced, dynamic environment."},
        {"section": "Experience", "mode": "replace",
         "original": "Designed PostgreSQL schemas and optimized queries to cut report generation time by 60%.",
         "suggested": "Partnered with numerous stakeholders across the organization to design, document, and maintain robust data solutions while driving operational excellence and ensuring adherence to best practices and quality standards."},
    ]),
]


# ---------------------------------------------------------------------------
# Scoring — replicates match.py's exact cosine pipeline (section-weighted is the
# primary cosine signal; whole-doc + experience are secondary/logged).
# ---------------------------------------------------------------------------

async def _score(resume_obj, jd_text, *, jd_emb):
    """Score one snapshot exactly as POST /api/match/ does: compute the real
    section-weighted cosine (R5 primary signal) via the production helpers, then
    feed it to score_resume_against_jd. Returns (result, chars, sec_weighted_raw)."""
    from app.api.match_logic.section_embedder import compute_section_cosine
    from app.api.match_logic.section_scorer import compute_experience_cosine, compute_section_cosines
    from app.core.vector_db import get_embedding
    from app.api.match_logic.hybrid_scorer import _SECTION_COS_WEIGHTS

    plaintext = resume_to_plaintext(resume_obj)
    resume_json = resume_obj.model_dump()

    section_cosine = await compute_section_cosine(resume_json, jd_text, get_embedding)
    exp_cos = await compute_experience_cosine(resume_obj, jd_emb, get_embedding)
    section_cosines = await compute_section_cosines(resume_obj, jd_emb, get_embedding)

    resume_emb = await get_embedding(plaintext)

    result = score_resume_against_jd(
        resume_text=plaintext,
        resume_json=resume_json,
        jd_text=jd_text,
        resume_embedding=resume_emb,
        jd_embedding=jd_emb,
        section_cosine=section_cosine,
        exp_section_cosine=exp_cos,
        section_cosines=section_cosines or None,
        resume_obj=resume_obj,
        log_event=False,  # never pollute score_log.jsonl from a diagnostic
    )
    # Reconstruct the raw section-weighted cosine for display.
    sec_raw = None
    if section_cosines:
        tot_w = sum(wt for s, wt in _SECTION_COS_WEIGHTS.items() if s in section_cosines)
        if tot_w > 0:
            sec_raw = sum(section_cosines[s] * wt for s, wt in _SECTION_COS_WEIGHTS.items()
                          if s in section_cosines) / tot_w
    return result, len(plaintext), sec_raw


# ---------------------------------------------------------------------------
# Remap sweep — show the p_low cliff directly
# ---------------------------------------------------------------------------

def _remap_sweep(w):
    span = max(w.p_high - w.p_low, 1e-6)
    print(f"\nCosine remap sweep  (p_low={w.p_low}, p_high={w.p_high}, w_cos={w.w_cos})")
    print(f"{'raw_cos':>8} | {'remapped':>8} | {'final pts (w_cos*100)':>22}")
    print("-" * 46)
    raw = 0.55
    while raw <= 0.80 + 1e-9:
        remapped = max(0.0, min(1.0, (raw - w.p_low) / span))
        pts = remapped * w.w_cos * 100
        flag = "  <- typical operating band" if 0.64 <= raw <= 0.73 else ""
        print(f"{raw:>8.3f} | {remapped:>8.3f} | {pts:>22.2f}{flag}")
        raw += 0.025


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_contrib_table(before: dict, after: dict):
    keys = ["keyword", "skill", "ngram", "edu", "seniority", "cosine"]
    bc, ac = before["feature_contributions"], after["feature_contributions"]
    print(f"\n{'signal':>10} | {'before':>7} | {'after':>7} | {'delta':>7}")
    print("-" * 40)
    for k in keys:
        b, a = bc.get(k, 0), ac.get(k, 0)
        d = a - b
        arrow = " UP " if d > 0 else (" DOWN" if d < 0 else "  =  ")
        print(f"{k:>10} | {b:>7} | {a:>7} | {d:>+6}{arrow}")


async def _amain():
    w = get_weights()
    print("=" * 64)
    print("REPRO: does continued tailoring LOWER the match score?")
    print("=" * 64)
    print(f"Active weights: w_kw={w.w_kw} w_skill={w.w_skill} w_ngram={w.w_ngram} "
          f"w_edu={w.w_edu} w_sen={w.w_sen} w_cos={w.w_cos}")
    print(f"Cosine remap:   p_low={w.p_low} p_high={w.p_high}")
    st = getattr(w, "spearman_test", None)
    if st is not None:
        print(f"Calibration generalization: spearman_test={st} "
              f"({'NEGATIVE - degenerate' if st <= 0 else 'positive'})")

    from app.core.vector_db import get_embedding
    try:
        jd_emb = await get_embedding(JD_TEXT)
    except Exception as e:
        print(f"\nEmbedding model unavailable ({type(e).__name__}: {e}); this diagnostic "
              f"needs it for the section-cosine signal. Aborting.")
        return
    print("\nCosine source: REAL embeddings (nomic), section-weighted (production path)")

    # Apply batches cumulatively, scoring after each via the real cosine pipeline.
    resume = build_sample_resume()
    stages: list[tuple[str, dict, int, float]] = []

    res, chars, sec = await _score(resume, JD_TEXT, jd_emb=jd_emb)
    stages.append(("0. base resume", res, chars, sec))
    for label, batch in BATCHES:
        resume = apply_suggestions(resume, batch)
        res, chars, sec = await _score(resume, JD_TEXT, jd_emb=jd_emb)
        stages.append((label, res, chars, sec))

    # Score curve (with raw section-weighted cosine alongside)
    print(f"\n{'stage':<48} | {'chars':>6} | {'sec_cos':>7} | {'score':>5}")
    print("-" * 78)
    prev = None
    peak = max(s[1]["score"] for s in stages)
    for label, res, chars, sec in stages:
        sc = res["score"]
        mark = ""
        if prev is not None:
            mark = "  UP" if sc > prev else ("  DOWN <--" if sc < prev else "  =")
        if sc == peak:
            mark += "  (peak)"
        sec_s = f"{sec:.3f}" if sec is not None else "  n/a"
        print(f"{label:<48} | {chars:>6} | {sec_s:>7} | {sc:>5}{mark}")
        prev = sc

    # Per-signal table: peak stage vs final stage (the inversion window)
    peak_idx = max(range(len(stages)), key=lambda i: stages[i][1]["score"])
    if peak_idx < len(stages) - 1:
        print(f"\nPer-signal change from PEAK ({stages[peak_idx][0]}) to FINAL ({stages[-1][0]}):")
        _print_contrib_table(stages[peak_idx][1], stages[-1][1])
        d = stages[-1][1]["score"] - stages[peak_idx][1]["score"]
        print(f"\nPEAK->FINAL score delta = {d:+d}")
        if d < 0:
            print("VERDICT: INVERSION CONFIRMED - more tailoring LOWERED the score once")
            print("         keyword/skill saturated; only cosine had headroom and it FELL.")
    else:
        print("\nVERDICT: no inversion in this run (score peaked at the final stage).")

    _remap_sweep(w)

    print("\nWhy: keyword/skill are set-based and rise, but SATURATE (cap at 100).")
    print("Past saturation only cosine has headroom - and cosine FALLS as added")
    print("content dilutes the section embeddings. The p_low cliff amplifies the")
    print("drop, so continued tailoring nets negative.")


def main():
    import asyncio
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
