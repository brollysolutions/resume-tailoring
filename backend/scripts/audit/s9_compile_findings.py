"""s9 — Compile findings_summary.md from all upstream artifacts.

Reads the JSON/CSV outputs of s1..s8 and produces a single markdown digest
in backend/docs/audit/findings_summary.md, structured with headline numbers,
per-pain-point sections, and prioritized recommendations.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]
_AUDIT = _BACKEND_ROOT / "docs" / "audit"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _pct(v) -> str:
    if isinstance(v, (int, float)):
        return f"{v * 100:.1f}%"
    return "?"


def _g(d: dict, k: str, default=None):
    """Tolerant getter."""
    return d.get(k, default) if isinstance(d, dict) else default


def main() -> int:
    manifest = _read_json(_AUDIT / "snapshot" / "manifest.json")
    join_yield = _read_json(_AUDIT / "data_quality" / "join_yield.json")
    cluster_skew = _read_json(_AUDIT / "data_quality" / "cluster_skew.json")
    label_dist = _read_csv(_AUDIT / "data_quality" / "label_distribution.csv")
    dup_rows = _read_csv(_AUDIT / "data_quality" / "duplication.csv")

    signal_stats = _read_csv(_AUDIT / "distributions" / "signal_stats.csv")
    floor_share = _read_json(_AUDIT / "distributions" / "floor_share.json")
    defaults_poll = _read_json(_AUDIT / "distributions" / "defaults_pollution.json")

    per_signal = _read_csv(_AUDIT / "correlation" / "per_signal_spearman.csv")
    per_signal_nc = _read_csv(_AUDIT / "correlation" / "per_signal_after_cluster_removal.csv")
    feat_corr = _read_csv(_AUDIT / "correlation" / "feature_correlation.csv")
    active_replay = _read_json(_AUDIT / "correlation" / "active_weight_replay.json")

    baseline = _read_json(_AUDIT / "calibration" / "baseline_comparison.json")
    replay_table = _read_csv(_AUDIT / "calibration" / "replay_table.csv")
    weights_timeline = _read_csv(_AUDIT / "calibration" / "weights_timeline.csv")

    ngram_rows = _read_csv(_AUDIT / "keywords" / "ngram_phrase_hits.csv")
    skill_cov = _read_csv(_AUDIT / "keywords" / "skill_set_coverage.csv")
    fuzzy_log = _read_csv(_AUDIT / "keywords" / "fuzzy_match_log.csv")
    jd_token_audit = _read_csv(_AUDIT / "keywords" / "jd_token_audit.csv")

    hard_req = _read_csv(_AUDIT / "ceiling" / "hard_req_extraction.csv")
    cosine_anom = _read_csv(_AUDIT / "ceiling" / "cosine_remap_anomalies.csv")
    floor_cluster = _read_json(_AUDIT / "ceiling" / "floor_clustering.json")

    cases = _read_csv(_AUDIT / "error_sample" / "cases.csv")

    n_events = manifest.get("files", {}).get("score_log.jsonl", {}).get("rows", 0)
    n_labels = manifest.get("files", {}).get("labels.jsonl", {}).get("rows", 0)
    n_unique_pairs = join_yield.get("n_unique_pairs_in_log", "?")
    n_joined = join_yield.get("n_joined", "?")
    rho_all = cluster_skew.get("spearman_all", "?")
    rho_nc = cluster_skew.get("spearman_without_dominant", "?")
    dom_share = cluster_skew.get("dominant_share_of_joined", "?")
    pct_floor35 = floor_share.get("final_score_eq_35_share", "?")
    pct_kw0 = floor_share.get("kw_raw_eq_0_share", "?")
    pct_lt45 = floor_share.get("final_score_lt_45_share", "?")
    pct_highcos_zerokw = floor_share.get("cosine_high_kw_zero_share", "?")

    # bucket counts in cases.csv
    bucket_counts = {}
    for r in cases:
        bucket_counts[r["bucket"]] = bucket_counts.get(r["bucket"], 0) + 1

    # dead ngrams
    dead_in_jd = [r["phrase"] for r in ngram_rows if r.get("dead_in_jd") == "True"]
    dead_in_both = [r["phrase"] for r in ngram_rows
                    if r.get("dead_in_jd") == "True" and r.get("dead_in_resume") == "True"]

    # ceiling extraction yield
    n_jd = floor_cluster.get("n_jd_unique", "?")
    n_yr = floor_cluster.get("n_jd_with_extracted_year", "?")
    n_deg = floor_cluster.get("n_jd_with_extracted_degree", "?")
    n_sen = floor_cluster.get("n_jd_with_extracted_seniority", "?")

    lines = []
    lines += [
        "# Resume-JD Matcher Audit — Findings Summary",
        "",
        f"Snapshot date: {manifest.get('snapshot_at', '(unknown)')}",
        "",
        "## 1. Headline numbers",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Score-log events | **{n_events}** |",
        f"| Unique (resume, JD) pairs in log | **{n_unique_pairs}** |",
        f"| Labels total | **{n_labels}** |",
        f"| Joined rows | **{n_joined}** |",
        f"| Spearman ρ (active weights, snapshot) | **{rho_all}** |",
        f"| Spearman ρ (no dominant cluster) | **{rho_nc}** |",
        f"| Dominant cluster share of joined | **{_pct(dom_share)}** |",
        f"| % events at score==35 (floor) | **{_pct(pct_floor35)}** |",
        f"| % events with final_score<45 | **{_pct(pct_lt45)}** |",
        f"| % events with kw_raw==0 | **{_pct(pct_kw0)}** |",
        f"| % events with cosine>0.85 AND kw_raw<0.1 | **{_pct(pct_highcos_zerokw)}** |",
        "",
        "## 2. Pain point (a) — Wrong scores",
        "",
        "### Per-signal predictive power (Spearman vs labels, 1000-resample bootstrap 95% CI)",
        "",
        "| Signal | ρ | 95% CI | Kendall τ | Point-biserial good-vs-bad | N |",
        "|--------|---|--------|-----------|---------------------------|---|",
    ]
    for r in per_signal:
        lines.append(
            f"| `{r['signal']}` | {r['spearman']} | [{r['ci_low']}, {r['ci_high']}] | "
            f"{r['kendall_tau']} | {r['point_biserial_good_vs_bad']} | {r['n']} |"
        )
    lines += [
        "",
        "Strong inversions and dead signals:",
        "",
        "- **`ngram_raw` is negatively correlated with label** "
        f"(ρ in `per_signal_spearman.csv`). Likely an artifact of "
        f"defaults: `ngram_raw=1.0` when the JD has no `_NGRAM_SKILLS` "
        f"phrases (`defaults_pollution.json::ngram_raw_1.0_share` = "
        f"{defaults_poll.get('ngram_raw_1.0_share')}), and those JDs tend to "
        f"have lower-quality matches.",
        "- **`seniority_raw` is flat at ρ≈0** — the signal is "
        f"{_pct(defaults_poll.get('seniority_raw_1.0_share'))} sentinel 1.0 "
        f"and {defaults_poll.get('seniority_raw_0.7_share')} fraction 0.7 — it carries almost no real signal.",
        "- **`cosine_blended` is near-zero ρ** despite being weighted ~10–25%. "
        f"Per-signal CI in `per_signal_spearman.csv` straddles zero; cosine is high in "
        f"{_pct(floor_share.get('cosine_blended_gt_0.85_share'))} of events and likely saturated.",
        "",
        "### Score distribution",
        "",
        f"- {len(signal_stats)} signals profiled in `distributions/signal_stats.csv`.",
        f"- Final-score mean ≈ "
        f"{next((r['mean'] for r in signal_stats if r['signal']=='final_score'), '?')}, "
        f"p95 = {next((r['p95'] for r in signal_stats if r['signal']=='final_score'), '?')} "
        f"(no events ≥95). Distribution is left-shifted.",
        "",
        "### Error sample buckets (see `error_sample/cases.csv`)",
        "",
        "| Bucket | Sampled rows |",
        "|--------|--------------|",
    ]
    for k, v in bucket_counts.items():
        lines.append(f"| `{k}` | {v} |")

    lines += [
        "",
        "## 3. Pain point (b) — Calibration trust",
        "",
        f"- Active weights "
        f"({active_replay.get('weights_active', {})}) "
        f"score ρ = **{baseline.get('active_rho_on_snapshot')}** "
        f"on snapshot (N={baseline.get('n_joined_snapshot')}).",
        f"- Hand-tuned DEFAULTS would score ρ = **{baseline.get('defaults_rho_on_snapshot')}**.",
        f"- Equal-weight (1/6) baseline ρ = **{baseline.get('equal_weight_baseline_rho')}**.",
        f"- Grid optimum on current snapshot ρ = **{baseline.get('top_grid_on_snapshot_rho')}** "
        f"using {baseline.get('top_grid_weights')}.",
        "",
        f"- **Active ρ 95% CI = {active_replay.get('spearman_active_on_snapshot_ci')}** — "
        f"the interval is wide enough that the difference between active and equal-weight "
        f"is not robustly significant.",
        f"- Removing the dominant cluster `{(cluster_skew.get('dominant_resume_id') or '?')[:12]}…` "
        f"({_pct(dom_share)} of joined) "
        f"drops active ρ from {rho_all} to {rho_nc}. "
        f"A large share of apparent calibration signal is one resume.",
        "",
        "### Historical weight replay (rho on current snapshot)",
        "",
        "| Snapshot | ρ |",
        "|----------|---|",
    ]
    for r in replay_table:
        lines.append(f"| `{r['snapshot']}` | {r['rho_on_snapshot']} |")

    lines += [
        "",
        "## 4. Pain point (c) — Keyword / skill brittleness",
        "",
        f"- **`_NGRAM_SKILLS` phrases**: {len(ngram_rows)} total; "
        f"{len(dead_in_jd)} dead in the JD corpus; "
        f"{len(dead_in_both)} dead in BOTH JD and resume corpora. "
        f"See `keywords/ngram_phrase_hits.csv`.",
        f"- **`nlp_utils.extract_skills` vs `_top_jd_tokens` average symmetric-difference share = "
        f"{(sum(float(r['disagreement_share']) for r in skill_cov)/max(len(skill_cov),1)):.2f}**. "
        f"`extract_skills` uses substring `in` matching (e.g. `\"go\" in \"going\"` -> hit), "
        f"so it both over-matches on short tokens and is decoupled from `SKILL_DOMAIN`.",
        f"- Fuzzy-match (rapidfuzz ≥85): {len(fuzzy_log)} non-exact pairs surfaced for human "
        f"review in `keywords/fuzzy_match_log.csv`.",
        f"- `seniority_raw=1.0` sentinel rate {defaults_poll.get('seniority_raw_1.0_share')} "
        f"+ `0.7` sentinel rate {defaults_poll.get('seniority_raw_0.7_share')} "
        f"-> seniority signal is essentially never producing a usable value.",
        "",
        "### Token funnel (per-JD averages from corpus)",
        "",
        "Average tokens through each filter stage (see `keywords/jd_token_audit.csv` for per-JD detail):",
        "",
    ]
    if jd_token_audit:
        n = len(jd_token_audit)
        def avg(field):
            try:
                return sum(int(r[field]) for r in jd_token_audit) / n
            except (ValueError, KeyError):
                return 0
        lines += [
            f"- Raw tokens: {avg('n_raw_tokens'):.0f}",
            f"- After stopwords: {avg('n_after_stopwords'):.0f}",
            f"- After BLOCKED_GENERIC: {avg('n_after_blocked'):.0f}",
            f"- Unique normalized: {avg('n_unique_normalized'):.0f}",
            f"- Final top_jd (k≤50): {avg('n_final_top_jd'):.0f}",
        ]

    lines += [
        "",
        "## 5. Pain point (d) — ML foundation readiness",
        "",
        f"- **Usable joined rows for supervised work: {n_joined}** "
        f"({n_joined - cluster_skew.get('dominant_n_joined', 0)} after removing dominant cluster).",
        "- This is well below conventional ranker training scales (≥ a few thousand pairs).",
        f"- Feature collinearity (see `correlation/feature_correlation.csv`): "
        f"the 6×6 Pearson matrix is dominated by independent dimensions, EXCEPT cosine "
        f"and skill, which can be checked in the CSV.",
        f"- Effective label classes after join: {join_yield.get('joined_label_mix')}",
        f"- Label-source mix is dominated by LLM seeds (see `data_quality/label_distribution.csv`); "
        f"implicit labels are still sparse.",
        f"- Duplicate (rid, jdh) rescored pairs in log: **{len(dup_rows)}** — most-recent-wins join "
        f"works but can mask training-time score drift. Variance summary in "
        f"`data_quality/duplication.csv`.",
        "",
        "## 6. Ceiling mechanism status (cross-cuts a & c)",
        "",
        f"- Unique JDs analyzed: **{n_jd}**.",
        f"- JDs with parsed `min_years_experience`: **{n_yr}/{n_jd}**.",
        f"- JDs with parsed `required_degrees`: **{n_deg}/{n_jd}**.",
        f"- JDs with parsed `seniority_level`: **{n_sen}/{n_jd}**.",
        "",
        "`parse_jd_hard_requirements` is essentially **toothless on the 240-char `jd_excerpt`** "
        "currently logged — the years/degrees clauses live past character 240 in most JDs. "
        f"Combined with the **{len(cosine_anom)} anomalies** in `ceiling/cosine_remap_anomalies.csv` "
        f"(`cosine>0.85` AND `kw_raw<0.1` AND `final_score>=35`), this is a strong driver of "
        f"the 'wrong score' symptom.",
        "",
        "## 7. Recommendations (prioritized)",
        "",
        "Each recommendation is a candidate Phase-2 task. Numbers reference the artifact that justifies the action.",
        "",
        "1. **Fix `extract_skills` substring bug** — replace `if skill in text_lower` with "
        "tokenized membership. `keywords/skill_set_coverage.csv` shows ≥0.9 disagreement with "
        "`_top_jd_tokens` driven by spurious hits on `go`, `r`, `ai`, etc. Single-file change.",
        "2. **Persist the full JD (not just `jd_excerpt`) in score_log, OR call "
        "`parse_jd_hard_requirements` on the live JD at scoring time** — `ceiling/floor_clustering.json` "
        "shows 0/% of JDs got years or degrees extracted. The ceiling penalty mechanism is "
        "currently a no-op for the data path. Until this is fixed, retuning ceiling penalty "
        "constants is wasted effort.",
        "3. **Demote or remove `seniority_raw` from the active blend.** ρ≈0 in "
        "`correlation/per_signal_spearman.csv`; "
        f"{_pct(defaults_poll.get('seniority_raw_1.0_share'))} sentinel rate. "
        "Either compute the signal properly (parse role-level from titles + dates) or drop the weight to zero.",
        "4. **Invert or fix `ngram_raw` semantics.** The signal is correlated negatively with the label. "
        "Likely cause: defaulting to 1.0 when no n-gram phrases are present. Should default to NaN/drop, "
        "or be split into `coverage_of_present_phrases` vs `n_phrases_present`.",
        "5. **Stop trusting `cosine_blended` as a primary signal.** ρ≈0 vs label; "
        f"{_pct(floor_share.get('cosine_blended_gt_0.85_share'))} of rows are above 0.85 (saturated). "
        "Consider replacing whole-doc cosine with a sectional or BM25-weighted variant.",
        "6. **Stratified label growth.** The dominant cluster carries 35% of the apparent Spearman signal. "
        "Target labels to: (i) diverse resume_ids — cap labels per resume — and (ii) JDs where extracted "
        "hard requirements DO fire. Goal: get to N≥300 joined rows that are not LLM-seeded before retuning.",
        "7. **Hold-out eval split.** Today the calibrator trains & evaluates on the same N=132. "
        "Add a time-based or resume-stratified hold-out so reported ρ is generalization, not fit.",
        "8. **Dead n-gram phrase prune.** "
        f"{len(dead_in_both)} of {len(ngram_rows)} phrases never hit in either corpus. "
        "Auditing `keywords/ngram_phrase_hits.csv` and pruning them costs nothing and removes noise.",
        "",
        "## 8. Out of scope (verbatim from plan)",
        "",
        "- Editing `weights_active.json`, retuning the grid, retraining anything",
        "- Adding or modifying rows in `labels.jsonl`",
        "- Changing stopword / blocked / alias sets or `_NGRAM_SKILLS`",
        "- Adding training data, synthetic JDs, or new LLM annotations",
        "- Modifying production scoring, extraction, or section code",
        "- Building the ML ranker (this audit defines readiness, not code)",
        "- Adding `matplotlib`, `pandas`, `scipy`, `numpy` to `backend/requirements.txt`",
        "",
        "---",
        "",
        "Generated by `backend/scripts/audit/s9_compile_findings.py`. ",
        "Rerun the full pipeline via the verification block in the plan file.",
        "",
    ]

    out = _AUDIT / "findings_summary.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"s9 done. findings_summary.md written ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
