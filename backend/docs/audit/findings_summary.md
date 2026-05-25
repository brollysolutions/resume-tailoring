# Resume-JD Matcher Audit — Findings Summary

Snapshot date: 2026-05-19T16:22:03.631122+00:00

## 1. Headline numbers

| Metric | Value |
|--------|-------|
| Score-log events | **607** |
| Unique (resume, JD) pairs in log | **137** |
| Labels total | **136** |
| Joined rows | **136** |
| Spearman ρ (active weights, snapshot) | **0.3431** |
| Spearman ρ (no dominant cluster) | **0.2231** |
| Dominant cluster share of joined | **20.6%** |
| % events at score==35 (floor) | **1.0%** |
| % events with final_score<45 | **45.8%** |
| % events with kw_raw==0 | **26.4%** |
| % events with cosine>0.85 AND kw_raw<0.1 | **30.5%** |

## 2. Pain point (a) — Wrong scores

### Per-signal predictive power (Spearman vs labels, 1000-resample bootstrap 95% CI)

| Signal | ρ | 95% CI | Kendall τ | Point-biserial good-vs-bad | N |
|--------|---|--------|-----------|---------------------------|---|
| `kw_raw` | 0.445 | [0.298, 0.576] | 0.611 | 0.465 | 136 |
| `skill_raw` | 0.311 | [0.175, 0.441] | 0.418 | 0.294 | 136 |
| `ngram_raw` | -0.325 | [-0.51, -0.12] | -0.642 | -0.33 | 136 |
| `edu_raw` | 0.152 | [0.023, 0.24] | 0.664 | 0.123 | 136 |
| `seniority_raw` | 0.0 | [0.0, 0.0] | 0.0 | 0.0 | 136 |
| `cosine_blended` | -0.015 | [-0.199, 0.176] | -0.033 | -0.087 | 136 |

Strong inversions and dead signals:

- **`ngram_raw` is negatively correlated with label** (ρ in `per_signal_spearman.csv`). Likely an artifact of defaults: `ngram_raw=1.0` when the JD has no `_NGRAM_SKILLS` phrases (`defaults_pollution.json::ngram_raw_1.0_share` = 0.3081), and those JDs tend to have lower-quality matches.
  - **R4 applied (2026-05-20).** `hybrid_scorer._ngram_signal` now returns `(coverage, active)` and `compute_signals` redistributes `w_ngram` into `w_kw` when `active=False` — JDs without n-gram phrases no longer get the artificial 1.0 boost. `score_log.jsonl` and `section_score_log.jsonl` gained two new fields: `ngram_coverage` (clean 0.0-when-inactive) and `ngram_active` (bool gate). `ngram_raw` is retained on the deprecation path (writes the legacy 1.0-sentinel-when-inactive value) so audit scripts s2/s3/s4/s5/s7/s8/s9 keep producing identical numbers. Calibration (`tune_weights`, `tune_section_weights`) reads the new fields and mirrors the runtime redistribution rule. Audit-script migration to `ngram_coverage` is a follow-up.
- **`seniority_raw` is flat at ρ≈0** — the signal is 96.5% sentinel 1.0 and 0.0346 fraction 0.7 — it carries almost no real signal.
- **`cosine_blended` is near-zero ρ** despite being weighted ~10–25%. Per-signal CI in `per_signal_spearman.csv` straddles zero; cosine is high in 53.0% of events and likely saturated.

### Score distribution

- 9 signals profiled in `distributions/signal_stats.csv`.
- Final-score mean ≈ 46.8764, p95 = 72.0 (no events ≥95). Distribution is left-shifted.

### Error sample buckets (see `error_sample/cases.csv`)

| Bucket | Sampled rows |
|--------|--------------|
| `high_score_bad_label` | 7 |
| `low_score_good_label` | 14 |
| `floor_no_ceiling_reason` | 22 |
| `high_cosine_zero_kw` | 16 |

## 3. Pain point (b) — Calibration trust

- Active weights ({'w_kw': 0.4, 'w_skill': 0.2, 'w_ngram': 0.05, 'w_edu': 0.1, 'w_sen': 0.15, 'w_cos': 0.1}) score ρ = **0.3431** on snapshot (N=136).
- Hand-tuned DEFAULTS would score ρ = **0.2265**.
- Equal-weight (1/6) baseline ρ = **0.1773**.
- Grid optimum on current snapshot ρ = **0.3431** using {'w_kw': 0.4, 'w_skill': 0.2, 'w_ngram': 0.05, 'w_edu': 0.1, 'w_sen': 0.15, 'w_cos': 0.1}.

- **Active ρ 95% CI = [0.1873, 0.4689]** — the interval is wide enough that the difference between active and equal-weight is not robustly significant.
- Removing the dominant cluster `5eac9e08-bbe…` (20.6% of joined) drops active ρ from 0.3431 to 0.2231. A large share of apparent calibration signal is one resume.

### Historical weight replay (rho on current snapshot)

| Snapshot | ρ |
|----------|---|
| `weights_active.json` | 0.3431 |
| `weights_2026-05-17T10-22-57.239574+00-00.json` | 0.2981 |
| `weights_2026-05-17T14-20-11.007573+00-00.json` | 0.2981 |
| `weights_2026-05-19T09-59-57.490385+00-00.json` | 0.3431 |

## 4. Pain point (c) — Keyword / skill brittleness

- **`_NGRAM_SKILLS` phrases**: 25 total; 3 dead in the JD corpus; 0 dead in BOTH JD and resume corpora. See `keywords/ngram_phrase_hits.csv`.
- **`nlp_utils.extract_skills` vs `_top_jd_tokens` average symmetric-difference share = 0.93**. `extract_skills` uses substring `in` matching (e.g. `"go" in "going"` -> hit), so it both over-matches on short tokens and is decoupled from `SKILL_DOMAIN`.
- Fuzzy-match (rapidfuzz ≥85): 22 non-exact pairs surfaced for human review in `keywords/fuzzy_match_log.csv`.
- `seniority_raw=1.0` sentinel rate 0.9654 + `0.7` sentinel rate 0.0346 -> seniority signal is essentially never producing a usable value.

### Token funnel (per-JD averages from corpus)

Average tokens through each filter stage (see `keywords/jd_token_audit.csv` for per-JD detail):

- Raw tokens: 282
- After stopwords: 208
- After BLOCKED_GENERIC: 194
- Unique normalized: 152
- Final top_jd (k≤50): 26

## 5. Pain point (d) — ML foundation readiness

- **Usable joined rows for supervised work: 136** (108 after removing dominant cluster).
- This is well below conventional ranker training scales (≥ a few thousand pairs).
- Feature collinearity (see `correlation/feature_correlation.csv`): the 6×6 Pearson matrix is dominated by independent dimensions, EXCEPT cosine and skill, which can be checked in the CSV.
- Effective label classes after join: {'bad': 106, 'ok': 6, 'good': 24}
- Label-source mix is dominated by LLM seeds (see `data_quality/label_distribution.csv`); implicit labels are still sparse.
- Duplicate (rid, jdh) rescored pairs in log: **38** — most-recent-wins join works but can mask training-time score drift. Variance summary in `data_quality/duplication.csv`.

## 6. Ceiling mechanism status (cross-cuts a & c)

- Unique JDs analyzed: **26**.
- JDs with parsed `min_years_experience`: **0/26**.
- JDs with parsed `required_degrees`: **0/26**.
- JDs with parsed `seniority_level`: **10/26**.

`parse_jd_hard_requirements` is essentially **toothless on the 240-char `jd_excerpt`** currently logged — the years/degrees clauses live past character 240 in most JDs. Combined with the **185 anomalies** in `ceiling/cosine_remap_anomalies.csv` (`cosine>0.85` AND `kw_raw<0.1` AND `final_score>=35`), this is a strong driver of the 'wrong score' symptom.

## 7. Recommendations (prioritized)

Each recommendation is a candidate Phase-2 task. Numbers reference the artifact that justifies the action.

1. **Fix `extract_skills` substring bug** — replace `if skill in text_lower` with tokenized membership. `keywords/skill_set_coverage.csv` shows ≥0.9 disagreement with `_top_jd_tokens` driven by spurious hits on `go`, `r`, `ai`, etc. Single-file change.
2. **Persist the full JD (not just `jd_excerpt`) in score_log, OR call `parse_jd_hard_requirements` on the live JD at scoring time** — `ceiling/floor_clustering.json` shows 0/% of JDs got years or degrees extracted. The ceiling penalty mechanism is currently a no-op for the data path. Until this is fixed, retuning ceiling penalty constants is wasted effort.
3. **Demote or remove `seniority_raw` from the active blend.** ρ≈0 in `correlation/per_signal_spearman.csv`; 96.5% sentinel rate. Either compute the signal properly (parse role-level from titles + dates) or drop the weight to zero.
4. **Invert or fix `ngram_raw` semantics.** The signal is correlated negatively with the label. Likely cause: defaulting to 1.0 when no n-gram phrases are present. Should default to NaN/drop, or be split into `coverage_of_present_phrases` vs `n_phrases_present`.
5. **Stop trusting `cosine_blended` as a primary signal.** ρ≈0 vs label; 53.0% of rows are above 0.85 (saturated). Consider replacing whole-doc cosine with a sectional or BM25-weighted variant.
6. **Stratified label growth.** The dominant cluster carries 35% of the apparent Spearman signal. Target labels to: (i) diverse resume_ids — cap labels per resume — and (ii) JDs where extracted hard requirements DO fire. Goal: get to N≥300 joined rows that are not LLM-seeded before retuning.
7. **Hold-out eval split.** Today the calibrator trains & evaluates on the same N=132. Add a time-based or resume-stratified hold-out so reported ρ is generalization, not fit.
8. **Dead n-gram phrase prune.** 0 of 25 phrases never hit in either corpus. Auditing `keywords/ngram_phrase_hits.csv` and pruning them costs nothing and removes noise.

## 8. Out of scope (verbatim from plan)

- Editing `weights_active.json`, retuning the grid, retraining anything
- Adding or modifying rows in `labels.jsonl`
- Changing stopword / blocked / alias sets or `_NGRAM_SKILLS`
- Adding training data, synthetic JDs, or new LLM annotations
- Modifying production scoring, extraction, or section code
- Building the ML ranker (this audit defines readiness, not code)
- Adding `matplotlib`, `pandas`, `scipy`, `numpy` to `backend/requirements.txt`

---

## Phase-2 shipped (post-snapshot)

- **R1** — `extract_skills` rewritten with `\b` word-boundary regex for atomic-alpha skills. Corpus skill matches dropped 122 → 75. (`backend/app/api/match_logic/nlp_utils.py`)
- **R8** — `_NGRAM_SKILLS` pruned 47 → 25 phrases. (`backend/app/core/keyword_utils.py`)
- **R2** — `score_log.jsonl` now records runtime ceiling outcome + JD hard-requirement extraction per scored event. New fields (authoritative going forward; supersedes re-parsing `jd_excerpt`): `ceiling_score`, `ceiling_reasons`, `exp_required`, `exp_actual`, `extracted_min_years`, `extracted_degrees`, `extracted_seniority`. Old rows have these as `null` / empty list. (`backend/app/api/match_logic/hybrid_scorer.py`, `backend/app/api/match.py`)

---

Generated by `backend/scripts/audit/s9_compile_findings.py`. 
Rerun the full pipeline via the verification block in the plan file.
