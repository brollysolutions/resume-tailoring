# Calibration Corpus

Drop-in inputs for `backend/scripts/calibration/seed_score_log.py`.

## Layout

```
calibration_corpus/
├── resumes/   ← PDFs or DOCXs. Filename used only for log readability.
└── jds/       ← .txt files, one JD each. Filename = JD slug.
```

## Guidance

- **Variety beats quantity for calibration.** Mix domains so the grid sees real spread: data, frontend, backend, ML/GenAI, DevOps, and at least 1-2 non-tech (marketing, finance, design).
- **Suggested mix:** 5-8 resumes × 8-12 JDs = 40-100 events per run.
- **Bad matches matter.** The cosine calibrator needs ≥5 `bad`-labeled pairs. Deliberately include resume×JD pairs you expect to mismatch (e.g., frontend resume vs data-engineering JD).
- Files are NOT committed (corpus is personal). Add a `.gitignore` entry if needed.

## Usage

```bash
# 1. Boot backend:    docker compose up       OR     uvicorn app.main:app ...
# 2. Run seeder:
python -m backend.scripts.calibration.seed_score_log
```

Re-running is safe — script dedups against existing `score_log.jsonl` entries by `(resume_id, jd_hash)`. Use `--no-skip-existing` to force re-matching.
