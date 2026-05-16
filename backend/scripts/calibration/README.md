# Hybrid Scorer Calibration

Offline workflow to tune the `(w_kw, w_skill, w_cos)` weights and the cosine remap
constants in `backend/app/api/match_logic/hybrid_scorer.py` against labeled
resume/JD pairs.

## Why

The shipped weights `0.55 / 0.25 / 0.20` and the cosine remap `(x - 0.3) / 0.7`
are hand-picked, not fit. Use this harness to replace both with empirically
calibrated values.

Not loaded by the API. Run by hand.

## Inputs

- `backend/data/score_log.jsonl` — written automatically by every call to
  `score_resume_against_jd`. Each event has `resume_id`, `jd_hash`,
  `jd_excerpt`, the raw component scores, and the final score.
- `backend/data/labels.jsonl` — produced by `label_ui.py`. One line per labeled
  pair: `{"resume_id":"...", "jd_hash":"...", "label":"good|ok|bad"}`.

## Trigger

Re-tune when both:
- `score_log.jsonl` has ≥ 100 entries (enough variance), AND
- `labels.jsonl` has ≥ 20 labeled pairs (enough signal).

## Workflow

```bash
# 0. (Optional but recommended) Batch-seed score_log.jsonl from a corpus of
#    resumes + JDs. Drop files into backend/data/calibration_corpus/ first.
#    See backend/data/calibration_corpus/README.md for layout.
#    Requires backend running (docker compose up OR local uvicorn).
python -m backend.scripts.calibration.seed_score_log

# 1. Label real pairs (interactive, human in the loop)
python -m backend.scripts.calibration.label_ui

# 2. Grid-search weights (prints top 5 + writes calibration_results.json)
python -m backend.scripts.calibration.tune_weights

# 3. Fit the cosine remap floor (prints p_low / p_high + sample before/after)
python -m backend.scripts.calibration.calibrate_cosine
```

`seed_score_log.py` uses `httpx` (transitive backend dep). The other three
are dep-free (hand-rolled Spearman, percentile, etc.) so they run in any
venv that boots the backend.

## Scripts

- `seed_score_log.py` — batch CLI. Walks `data/calibration_corpus/resumes/`
  and `data/calibration_corpus/jds/`, uploads every resume via
  `POST /api/resume/upload`, then `POST /api/match/` for every
  `(resume_id, jd_text)` pair. Dedups against `score_log.jsonl` by
  `(resume_id, jd_hash)` so re-runs are safe. Concurrency capped at 4 by
  default (embedder + LLM are CPU-bound).

- `label_ui.py` — CLI loop. Deduplicates `(resume_id, jd_hash)` pairs against
  `labels.jsonl`, fetches the resume text from Qdrant for context, prompts
  `g/o/b/s/q`, appends to `labels.jsonl` immediately (no batch loss on quit).

- `tune_weights.py` — grid-searches `(w_kw, w_skill, w_cos)` over
  `w_kw ∈ {0.40..0.70}`, `w_skill ∈ {0.10..0.35}`, `w_cos = 1 - w_kw - w_skill`
  (clamped to `[0.05, 0.40]`). Optimizes Spearman correlation against labels
  (`good=2, ok=1, bad=0`); reports Kendall's tau alongside. Exits with a
  warning if best Spearman < 0.3 or joined rows < 10.

- `calibrate_cosine.py` — fits the cosine remap on `bad`-labeled rows. Uses
  the 5th and 95th percentile of `whole_doc_cos_raw` across bad pairs as the
  new `(p_low, p_high)` anchors. Warns if fewer than 5 bad rows or if the
  p5/p95 spread is < 0.05.

## Applying the result

Both tuners print a copy-pasteable code line at the end. Manual steps:

1. Edit `backend/app/api/match_logic/hybrid_scorer.py`:
   - Update the `raw_score = (bm25_score * w_kw) + ...` line with the new
     triple from `tune_weights.py`.
   - Update the `whole_doc_cos = max(0.0, (raw - 0.3) / 0.7)` AND
     `section_cos_remapped = max(0.0, (section_cosine - 0.3) / 0.7)` lines
     with the new `(p_low, p_high)` anchors from `calibrate_cosine.py`.
2. Add a comment block above the changed constants documenting the run:
   ```python
   # Calibrated YYYY-MM-DD on N=42 labeled pairs.
   # Spearman = 0.61, Kendall tau = 0.49.
   # See backend/data/calibration_results.json for the full grid.
   ```
3. Code-review, deploy.

## Out of scope

- Automating the source edit. Scripts only print recommendations — a script
  writing back into `hybrid_scorer.py` would be risky and discourages the
  human review step.
- Per-section weight calibration. Section scores currently reuse the
  whole-resume formula. Decide separately whether sections need their own
  grid once the whole-resume weights are real.
