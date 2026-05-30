# Test Findings — Match % + Tailor build-out

Generated while expanding the automated test suite (offline-mocked) across every
endpoint, with extra depth on the Match % engine and the tailor endpoints, plus
an opt-in live smoke set. **Report-only: no app/source code was changed.** The
only edits to non-test files would be the *proposed* fixes below; the test
additions and the test-isolation fixture are test infrastructure only.

## Run summary

| Suite | Result |
|---|---|
| `pytest tests/unit tests/api` (offline) | **198 passed, 1 failed** (F4) |
| `tests/integration/test_live_smoke.py` (no `RUN_LIVE`) | 5 skipped (as designed) |
| `backend/data/*.jsonl` after a full run | **unchanged** (F2 fixture works) |

Baseline before this work: 110 passed / 1 failed in `unit+api`. Added **88** new
offline tests + **5** opt-in live tests. The single remaining failure (F4) is
**pre-existing on `main`**, not introduced here.

## Findings

| ID | Severity | Area | One-liner |
|----|----------|------|-----------|
| F1 | Low | docs / dead code | `/api/tailor/preprocess-jd` documented but no route + no caller; `preprocess_jd()` is dead |
| F2 | Medium | test hygiene / CI | API tests appended to committed `data/*.jsonl` (loggers unmocked) |
| F3 | Low | tailor API | `/api/tailor/generate-projects` `count` is unbounded (no clamp) |
| F4 | Medium | ATS scoring | `test_parse_score_missing_email_and_phone` red on `main`: asserts `<=60`, code yields `65` |

---

### F1 — `preprocess-jd` documented but does not exist
- **Where**: `app/core/llm_helpers.py:689` (`async def preprocess_jd`); referenced by `docs/TESTING.md` Stage 2 and `CLAUDE.md` as `/api/tailor/preprocess-jd`.
- **Evidence**: no `@router` exposes it (`tailor.py` has no `preprocess` route); `grep` of `frontend/**/*.tsx` for `preprocess` returns **0 hits**. The job-search page's "auto-clean" the docs describe is not actually called.
- **Impact**: dead helper; misleading docs/test recipe (anyone following TESTING.md will 404).
- **Proposed fix** (pick one): (a) delete `preprocess_jd` and remove the `/preprocess-jd` references from `docs/TESTING.md` + `CLAUDE.md`; or (b) if auto-clean is still wanted, add a `POST /api/tailor/preprocess-jd` route that calls the helper and wire it into `job-search/page.tsx`.

### F2 — API test suite mutated committed data logs *(fixed in test infra)*
- **Where**: `tests/api/conftest.py` mocked Qdrant/embedding/LLM/cache but not the jsonl writers:
  `app.api.match._log_section_delta`, `app.api.match_logic.hybrid_scorer._log_score_event`,
  `app.api.match_logic.section_scorer._log_section_event`, `app.core.implicit_labeler.log_suggestion_event`,
  `app.api.resume._log_upload_event`.
- **Evidence**: running `tests/api` appended rows to `backend/data/section_deltas.jsonl`,
  `section_score_log.jsonl`, `suggestion_events.jsonl`, `upload_events.jsonl`, `score_log.jsonl`
  (all show `M` in `git status`). `docs/TESTING.md` §D claims the suite is "side-effect free" — it was not.
- **Action taken (test infra)**: added an autouse `patch_data_logs` fixture in `tests/api/conftest.py`
  neutralizing those five writers. Verified: jsonl line counts are byte-identical before/after a full run.
- **Proposed source-side fix**: gate the writers on a `TESTING` env flag, or redirect the `data/`
  path (the `_DATA` / `_SCORE_LOG_PATH` / `_SECTION_LOG_PATH` constants) to a temp dir under test,
  so the loggers are inert regardless of which suite invokes them.

### F3 — `generate-projects` count is unbounded
- **Where**: `app/api/tailor.py` `GenerateProjectsRequest.count: int = 3`; `generate_projects` loops up
  to 3 attempts each requesting `count` candidates with no clamp.
- **Evidence**: `count=0` returns `{"projects": []}` (documented by `test_generate_projects_count_zero_returns_empty`);
  a large `count` fans out 3× large LLM synthesis calls; negatives are accepted by Pydantic.
- **Impact**: low (user-triggered), but a malformed/abusive `count` wastes LLM budget / latency.
- **Proposed fix**: clamp on entry, e.g. `count = max(1, min(request.count, 6))`.

### F4 — ATS parse-score test is red on `main`
- **Where**: `tests/unit/test_ats_simulator.py:144` vs `app/core/ats_simulator.py:_compute_parse_score`.
- **Repro**: `_compute_parse_score(["email", "phone"], [])` → `100 − 20 (email) − 15 (phone) = 65`;
  the test asserts `score <= 60`.
- **Impact**: the suite is **not green on `main`** today; CI gating on `pytest` would fail.
- **Proposed fix** (decide intended weights, then ONE of):
  - bump the penalties so missing both contact fields lands ≤60 (e.g. email 25 + phone 18), **or**
  - relax the assertion to `<= 65` if 65 is the intended score.
  Needs a product call on how harshly missing email+phone should score — left unchanged pending your decision.

## Observations (lower-confidence; behavior locked by new tests, not necessarily bugs)

- **O1 — Match score is not capped by the ceiling.** `score_resume_against_jd` computes `ceiling`
  only for logging; `/api/match/` returns the raw blended `score` and `ceiling` as *separate* fields.
  A candidate who fails a hard requirement (e.g. 2 yrs vs 5 required) can still show a high `score`.
  This appears intentional (see `improvement_planner` comment), but confirm it's the desired UX.
- **O2 — Snapshot caches aren't weight-versioned.** `_ORIGINAL_SNAPSHOT_CACHE` (keyed `(resume_id, jd_hash)`)
  and the redis `tailored_match_v3` key are not invalidated when the auto-calibrator swaps weights, so a
  cached "original" / `delta` can be stale after a calibration cycle (bounded by 24h TTL).
- **O3 — Seniority treated differently across the two paths.** When a candidate's title has no
  detectable level, `hybrid_scorer._seniority_signal` assumes "mid" (idx 1) while
  `ceiling_detector.detect_ceiling` assumes below-junior (idx −1 → larger penalty). Same input, very
  different treatment — fine if deliberate (soft signal vs hard ceiling), but worth a conscious decision.

## New / extended tests

Offline (mocked, CI-safe):
- **Match % engine (unit):** `test_hybrid_scorer.py` (new), `test_gap_analyzer.py` (new),
  `test_section_scorer.py` (new), `test_diagnose_score.py` (new), `test_ceiling_detector.py` (extended:
  `detect_ceiling` / `infer_seniority` / `resume_has_degree`).
- **Endpoints (api):** `test_match_api.py` (validation branches, response shape, delta math, snapshot
  stability, 500-on-bad-json, guidance no-LLM path), `test_tailor_api.py` (bucketing, intensity→iters,
  thread-cache hit, density forwarding, 422/404 paths, skills intensity override, refresh add-mode drop,
  count=0), `test_tailor_helpers.py` (new: `_scrub_locations` / `_fix_project_name` / `_replace_projects`),
  `test_resume_api.py` (413, docx, partial PATCH), `test_admin_api.py` (`updated=True`).
- **Infra:** `tests/api/conftest.py` autouse `patch_data_logs` fixture (F2).

Opt-in live (real embedding + LLM + Qdrant): `tests/integration/test_live_smoke.py` — scaffold → match
→ tailored → suggestions → apply-pdf. Skipped unless `RUN_LIVE=1` and a provider key are set.

## How to run

```powershell
cd backend
.\venv\Scripts\Activate.ps1

pytest tests/unit tests/api -q          # offline, ~14s — should be all-green once F4 is reconciled
git status --short data/                 # expect NO new 'M' on *.jsonl after the run (F2)

# Live smoke (needs Qdrant up + a provider key):
$env:RUN_LIVE = "1"
pytest tests/integration/test_live_smoke.py -v
```
