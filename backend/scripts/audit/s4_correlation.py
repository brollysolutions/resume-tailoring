"""s4 — Per-signal correlation with label, bootstrap CIs, collinearity.

Joins snapshot/score_log + snapshot/labels via tune_weights._join, then for each
of the six raw signals reports Spearman/Kendall and a 1000-resample bootstrap
95% CI. Repeats with the dominant single-resume cluster removed. Builds a
Pearson 6x6 collinearity matrix. Replays the active weights from
weights_active.json against the snapshot and reports current Spearman.
"""
from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path

from backend.scripts.calibration.tune_weights import (
    _join,
    _kendall_tau,
    _load_jsonl,
    _pearson,
    _spearman,
)

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_SNAP = _BACKEND / "docs" / "audit" / "snapshot"
_OUT = _BACKEND / "docs" / "audit" / "correlation"

_SIGNALS = ["kw_raw", "skill_raw", "ngram_raw", "edu_raw", "seniority_raw", "cosine_blended"]
_BOOTSTRAP_N = 1000


def _bootstrap_ci_spearman(signal: list[float], truth: list[float], n: int = _BOOTSTRAP_N
                           ) -> tuple[float, float, float]:
    """Return (point, ci_low, ci_high) Spearman."""
    rng = random.Random(0)
    point = _spearman(signal, truth)
    if len(signal) < 4:
        return point, point, point
    size = len(signal)
    samples = []
    for _ in range(n):
        idxs = [rng.randrange(size) for _ in range(size)]
        xs = [signal[i] for i in idxs]
        ys = [truth[i] for i in idxs]
        samples.append(_spearman(xs, ys))
    samples.sort()
    lo = samples[int(0.025 * len(samples))]
    hi = samples[int(0.975 * len(samples)) - 1]
    return point, lo, hi


def _point_biserial(values: list[float], labels: list[str]) -> float:
    """good=1, bad=0; ok rows dropped."""
    pairs = [(v, 1) if l == "good" else (v, 0) for v, l in zip(values, labels)
             if l in ("good", "bad")]
    if len(pairs) < 4:
        return 0.0
    xs = [p[0] for p in pairs]
    ys = [float(p[1]) for p in pairs]
    return _pearson(xs, ys)


def _per_signal_table(joined: list[dict]) -> list[dict]:
    truth = [r["label_value"] for r in joined]
    labels_str = [r["label"] for r in joined]
    out = []
    for sig in _SIGNALS:
        vals = [r[sig] for r in joined]
        rho, lo, hi = _bootstrap_ci_spearman(vals, truth)
        tau = _kendall_tau(vals, truth)
        pb = _point_biserial(vals, labels_str)
        out.append({
            "signal": sig,
            "spearman": round(rho, 3),
            "ci_low": round(lo, 3),
            "ci_high": round(hi, 3),
            "kendall_tau": round(tau, 3),
            "point_biserial_good_vs_bad": round(pb, 3),
            "n": len(vals),
        })
    return out


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    log = _load_jsonl(_SNAP / "score_log.jsonl")
    labels = _load_jsonl(_SNAP / "labels.jsonl")
    weights = json.loads((_SNAP / "weights_active.json").read_text())
    joined = _join(log, labels)
    if not joined:
        print("s4: no joined rows; abort")
        return 1

    # dominant cluster id
    dominant_rid = Counter(r["resume_id"] for r in joined).most_common(1)[0][0]

    # per_signal_spearman.csv (all rows)
    all_table = _per_signal_table(joined)
    fields = ["signal", "spearman", "ci_low", "ci_high", "kendall_tau",
              "point_biserial_good_vs_bad", "n"]
    with (_OUT / "per_signal_spearman.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(all_table)

    # per_signal_after_cluster_removal.csv
    joined_nc = [r for r in joined if r["resume_id"] != dominant_rid]
    nc_table = _per_signal_table(joined_nc) if joined_nc else []
    with (_OUT / "per_signal_after_cluster_removal.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields + ["excluded_resume_id"])
        wr.writeheader()
        for row in nc_table:
            wr.writerow({**row, "excluded_resume_id": dominant_rid})

    # feature_correlation.csv — Pearson 6x6 across raw signals
    columns = {sig: [r[sig] for r in joined] for sig in _SIGNALS}
    rows = []
    for s1 in _SIGNALS:
        row = {"signal": s1}
        for s2 in _SIGNALS:
            row[s2] = round(_pearson(columns[s1], columns[s2]), 3)
        rows.append(row)
    with (_OUT / "feature_correlation.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["signal"] + _SIGNALS)
        wr.writeheader()
        wr.writerows(rows)

    # active_weight_replay.json
    truth = [r["label_value"] for r in joined]

    def predicted(rows_, w):
        return [
            w["w_kw"] * r["kw_raw"]
            + w["w_skill"] * r["skill_raw"]
            + w["w_ngram"] * r["ngram_raw"]
            + w["w_edu"] * r["edu_raw"]
            + w["w_sen"] * r["seniority_raw"]
            + w["w_cos"] * r["cosine_blended"]
            for r in rows_
        ]

    pred_all = predicted(joined, weights)
    rho_active = _spearman(pred_all, truth)
    rho_active_p, lo_a, hi_a = _bootstrap_ci_spearman(pred_all, truth)

    # equal-weight 1/6 baseline
    equal_w = {"w_kw": 1/6, "w_skill": 1/6, "w_ngram": 1/6,
               "w_edu": 1/6, "w_sen": 1/6, "w_cos": 1/6}
    pred_eq = predicted(joined, equal_w)
    rho_eq = _spearman(pred_eq, truth)

    # without dominant cluster
    truth_nc = [r["label_value"] for r in joined_nc]
    pred_nc_active = predicted(joined_nc, weights) if joined_nc else []
    rho_active_nc = _spearman(pred_nc_active, truth_nc) if joined_nc else 0.0

    replay = {
        "weights_active": {k: weights[k] for k in
                           ["w_kw", "w_skill", "w_ngram", "w_edu", "w_sen", "w_cos"]},
        "weights_active_calibrated_at": weights.get("calibrated_at"),
        "weights_active_reported_spearman": weights.get("spearman"),
        "snapshot_n_joined": len(joined),
        "spearman_active_on_snapshot": round(rho_active, 4),
        "spearman_active_on_snapshot_ci": [round(lo_a, 4), round(hi_a, 4)],
        "spearman_active_no_cluster": round(rho_active_nc, 4),
        "spearman_equal_weights_baseline": round(rho_eq, 4),
        "dominant_resume_id": dominant_rid,
    }
    (_OUT / "active_weight_replay.json").write_text(
        json.dumps(replay, indent=2), encoding="utf-8"
    )

    print(f"s4 done. active_rho={replay['spearman_active_on_snapshot']} "
          f"CI={replay['spearman_active_on_snapshot_ci']} "
          f"no_cluster={replay['spearman_active_no_cluster']} "
          f"equal_baseline={replay['spearman_equal_weights_baseline']}")
    for row in all_table:
        print(f"  {row['signal']:15s} rho={row['spearman']:>6.3f}  "
              f"CI=[{row['ci_low']:>6.3f},{row['ci_high']:>6.3f}]  "
              f"tau={row['kendall_tau']:>6.3f}  pb={row['point_biserial_good_vs_bad']:>6.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
