"""s2 — Data quality and label-integrity audit.

Reads the frozen snapshot, characterizes label cluster skew, joins
score_log<->labels using the same convention as tune_weights, and quantifies
the Spearman headline both with and without the dominant single-resume cluster.

Outputs under backend/docs/audit/data_quality/:
    label_distribution.csv
    join_yield.json
    duplication.csv
    cluster_skew.json
    quality_report.md
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from backend.scripts.calibration.tune_weights import (
    _LABEL_VALUE,
    _join,
    _load_jsonl,
    _spearman,
)

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_SNAP = _BACKEND / "docs" / "audit" / "snapshot"
_OUT = _BACKEND / "docs" / "audit" / "data_quality"


def _active_weights_score(row: dict, w: dict) -> float:
    return (
        w["w_kw"] * row["kw_raw"]
        + w["w_skill"] * row["skill_raw"]
        + w["w_ngram"] * row["ngram_raw"]
        + w["w_edu"] * row["edu_raw"]
        + w["w_sen"] * row["seniority_raw"]
        + w["w_cos"] * row["cosine_blended"]
    )


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)

    log = _load_jsonl(_SNAP / "score_log.jsonl")
    labels = _load_jsonl(_SNAP / "labels.jsonl")
    weights_active = json.loads((_SNAP / "weights_active.json").read_text())

    # --- label_distribution.csv ---
    per_resume: dict[str, Counter] = defaultdict(Counter)
    per_resume_sources: dict[str, Counter] = defaultdict(Counter)
    for lab in labels:
        rid = lab.get("resume_id") or "(missing)"
        label = lab.get("label") or "(missing)"
        src = lab.get("source") or "(missing)"
        per_resume[rid][label] += 1
        per_resume_sources[rid][src] += 1

    label_dist_rows = []
    for rid, lc in per_resume.items():
        total = sum(lc.values())
        label_dist_rows.append({
            "resume_id": rid,
            "n_labels": total,
            "good": lc.get("good", 0),
            "ok": lc.get("ok", 0),
            "bad": lc.get("bad", 0),
            "src_llm": per_resume_sources[rid].get("llm", 0),
            "src_implicit": per_resume_sources[rid].get("implicit", 0),
        })
    label_dist_rows.sort(key=lambda r: r["n_labels"], reverse=True)
    with (_OUT / "label_distribution.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(label_dist_rows[0].keys()) if label_dist_rows else
                            ["resume_id", "n_labels", "good", "ok", "bad", "src_llm", "src_implicit"])
        wr.writeheader()
        wr.writerows(label_dist_rows)

    # --- join_yield.json ---
    unique_pairs_in_log = {(ev.get("resume_id") or "", ev.get("jd_hash") or "")
                           for ev in log if ev.get("jd_hash")}
    joined = _join(log, labels)
    joined_keys = {(r["resume_id"], r["jd_hash"]) for r in joined}
    labels_with_known_value = [l for l in labels if l.get("label") in _LABEL_VALUE]
    label_keys = {(l.get("resume_id") or "", l.get("jd_hash") or "")
                  for l in labels_with_known_value}
    lost = label_keys - joined_keys
    join_label_mix = Counter(r["label"] for r in joined)
    join_yield = {
        "n_log_events": len(log),
        "n_unique_pairs_in_log": len(unique_pairs_in_log),
        "n_labels_total": len(labels),
        "n_labels_with_valid_value": len(labels_with_known_value),
        "n_joined": len(joined),
        "n_lost_to_missing_log": len(lost),
        "joined_label_mix": dict(join_label_mix),
        "weights_active_n_rows": weights_active.get("n_rows"),
        "weights_active_spearman": weights_active.get("spearman"),
    }
    (_OUT / "join_yield.json").write_text(json.dumps(join_yield, indent=2), encoding="utf-8")

    # --- duplication.csv ---
    by_pair: dict[tuple, list[float]] = defaultdict(list)
    for ev in log:
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        if not jdh:
            continue
        try:
            fs = float(ev.get("final_score") or 0)
        except (TypeError, ValueError):
            continue
        by_pair[(rid, jdh)].append(fs)

    dup_rows = []
    for (rid, jdh), scores in by_pair.items():
        if len(scores) <= 1:
            continue
        mean = sum(scores) / len(scores)
        var = sum((s - mean) ** 2 for s in scores) / len(scores)
        dup_rows.append({
            "resume_id": rid,
            "jd_hash": jdh,
            "n_events": len(scores),
            "min_score": round(min(scores), 2),
            "max_score": round(max(scores), 2),
            "range": round(max(scores) - min(scores), 2),
            "stdev": round(var ** 0.5, 3),
        })
    dup_rows.sort(key=lambda r: r["range"], reverse=True)
    with (_OUT / "duplication.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["resume_id", "jd_hash", "n_events",
                                           "min_score", "max_score", "range", "stdev"])
        wr.writeheader()
        wr.writerows(dup_rows)

    # --- cluster_skew.json ---
    # The dominant cluster is the resume_id with the most joined rows.
    join_per_resume = Counter(r["resume_id"] for r in joined)
    dominant_rid, dominant_n = (join_per_resume.most_common(1) or [("", 0)])[0]

    truth_all = [r["label_value"] for r in joined]
    pred_all = [_active_weights_score(r, weights_active) for r in joined]
    rho_all = _spearman(pred_all, truth_all)

    joined_no_cluster = [r for r in joined if r["resume_id"] != dominant_rid]
    truth_nc = [r["label_value"] for r in joined_no_cluster]
    pred_nc = [_active_weights_score(r, weights_active) for r in joined_no_cluster]
    rho_no_cluster = _spearman(pred_nc, truth_nc) if joined_no_cluster else 0.0

    cluster_label_mix = Counter(r["label"] for r in joined if r["resume_id"] == dominant_rid)
    cluster_skew = {
        "dominant_resume_id": dominant_rid,
        "dominant_n_joined": dominant_n,
        "dominant_label_mix": dict(cluster_label_mix),
        "dominant_share_of_joined": round(dominant_n / max(len(joined), 1), 3),
        "spearman_all": round(rho_all, 4),
        "spearman_without_dominant": round(rho_no_cluster, 4),
        "spearman_delta": round(rho_all - rho_no_cluster, 4),
        "n_joined_all": len(joined),
        "n_joined_no_cluster": len(joined_no_cluster),
    }
    (_OUT / "cluster_skew.json").write_text(
        json.dumps(cluster_skew, indent=2), encoding="utf-8"
    )

    # --- quality_report.md ---
    report = [
        "# Data Quality Report",
        "",
        f"Joined rows: **{len(joined)}** of {len(labels)} labels "
        f"(lost to missing log: {len(lost)})",
        f"Unique pairs in log: {len(unique_pairs_in_log)}; "
        f"log events: {len(log)} (avg {len(log)/max(len(unique_pairs_in_log),1):.1f} events/pair)",
        "",
        "## Label cluster skew",
        "",
        f"- Dominant resume_id: `{dominant_rid}` -> **{dominant_n}** joined rows "
        f"({cluster_skew['dominant_share_of_joined']*100:.1f}% of joined)",
        f"- Label mix in cluster: {dict(cluster_label_mix)}",
        f"- Active-weights Spearman over all joined rows: **{cluster_skew['spearman_all']}**",
        f"- Active-weights Spearman with cluster removed: **{cluster_skew['spearman_without_dominant']}**",
        f"- Delta (cluster contribution): {cluster_skew['spearman_delta']}",
        "",
        "## Top 10 resumes by label count",
        "",
        "| resume_id | n_labels | good | ok | bad | llm | implicit |",
        "|-----------|----------|------|----|-----|-----|----------|",
    ]
    for r in label_dist_rows[:10]:
        report.append(
            f"| `{r['resume_id'][:12]}...` | {r['n_labels']} | {r['good']} | "
            f"{r['ok']} | {r['bad']} | {r['src_llm']} | {r['src_implicit']} |"
        )
    report.append("")
    report.append(f"## Duplication")
    report.append("")
    report.append(f"Pairs rescored more than once: **{len(dup_rows)}**")
    if dup_rows:
        top = dup_rows[0]
        report.append(f"Largest range: pair `({top['resume_id'][:8]}, {top['jd_hash']})` "
                      f"-> {top['n_events']} events, span {top['range']} points")
    report.append("")
    (_OUT / "quality_report.md").write_text("\n".join(report), encoding="utf-8")

    print(f"s2 done. joined={len(joined)} dominant_rid={dominant_rid[:12]}... "
          f"share={cluster_skew['dominant_share_of_joined']:.1%} "
          f"rho_all={cluster_skew['spearman_all']} rho_no_cluster={cluster_skew['spearman_without_dominant']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
