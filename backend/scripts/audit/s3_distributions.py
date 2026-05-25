"""s3 — Score and per-signal distribution audit.

Inputs:  snapshot/score_log.jsonl
Outputs under backend/docs/audit/distributions/:
    signal_stats.csv      — mean/std/percentiles + frac-zero/one per signal
    defaults_pollution.json — frac of rows where ngram/edu/seniority are at sentinel defaults
    floor_share.json      — frac at ceiling floor, frac with kw_raw==0, frac cosine>0.85
    signal_histograms.png  — only if matplotlib importable (optional)
    final_score_hist.png   — optional
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from backend.scripts.calibration.tune_weights import _load_jsonl

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_SNAP = _BACKEND / "docs" / "audit" / "snapshot"
_OUT = _BACKEND / "docs" / "audit" / "distributions"

_SIGNALS = [
    "kw_raw",
    "skill_raw",
    "ngram_raw",
    "edu_raw",
    "seniority_raw",
    "cosine_blended",
    "whole_doc_cos_raw",
    "exp_cos_raw",
    "final_score",
]


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    s = sorted(values)
    n = len(s)
    return {
        "n": n,
        "mean": round(sum(s) / n, 4),
        "std": round(statistics.pstdev(s), 4) if n > 1 else 0.0,
        "p05": round(_percentile(s, 0.05), 4),
        "p25": round(_percentile(s, 0.25), 4),
        "p50": round(_percentile(s, 0.50), 4),
        "p75": round(_percentile(s, 0.75), 4),
        "p95": round(_percentile(s, 0.95), 4),
        "frac_zero": round(sum(1 for v in s if v == 0.0) / n, 4),
        "frac_one":  round(sum(1 for v in s if v == 1.0) / n, 4),
        "min": round(s[0], 4),
        "max": round(s[-1], 4),
    }


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    log = _load_jsonl(_SNAP / "score_log.jsonl")

    # Coerce values; missing -> None (filtered) rather than substituting defaults,
    # so the distribution shows what was actually logged.
    columns: dict[str, list[float]] = {sig: [] for sig in _SIGNALS}
    n_total = 0
    for row in log:
        n_total += 1
        for sig in _SIGNALS:
            v = row.get(sig)
            if v is None:
                continue
            try:
                columns[sig].append(float(v))
            except (TypeError, ValueError):
                pass

    # signal_stats.csv
    stats_rows = []
    for sig in _SIGNALS:
        s = _stats(columns[sig])
        s["signal"] = sig
        stats_rows.append(s)
    fields = ["signal", "n", "mean", "std", "p05", "p25", "p50", "p75", "p95",
              "frac_zero", "frac_one", "min", "max"]
    with (_OUT / "signal_stats.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for row in stats_rows:
            wr.writerow({k: row.get(k, "") for k in fields})

    # defaults_pollution.json — separate "sentinel default" rows from genuine 1.0/0.7
    sentinel = {
        "ngram_raw_1.0_share": 0.0,
        "edu_raw_1.0_share": 0.0,
        "seniority_raw_1.0_share": 0.0,
        "seniority_raw_0.7_share": 0.0,
    }
    if n_total:
        sentinel["ngram_raw_1.0_share"] = round(
            sum(1 for r in log if (r.get("ngram_raw") == 1.0 or r.get("ngram_raw") == 1)) / n_total, 4
        )
        sentinel["edu_raw_1.0_share"] = round(
            sum(1 for r in log if (r.get("edu_raw") == 1.0 or r.get("edu_raw") == 1)) / n_total, 4
        )
        sentinel["seniority_raw_1.0_share"] = round(
            sum(1 for r in log if (r.get("seniority_raw") == 1.0 or r.get("seniority_raw") == 1)) / n_total, 4
        )
        sentinel["seniority_raw_0.7_share"] = round(
            sum(1 for r in log if r.get("seniority_raw") == 0.7) / n_total, 4
        )
    sentinel["n_total"] = n_total
    (_OUT / "defaults_pollution.json").write_text(
        json.dumps(sentinel, indent=2), encoding="utf-8"
    )

    # floor_share.json
    floor_share = {
        "n_total": n_total,
        "final_score_eq_35_share": 0.0,
        "final_score_lt_45_share": 0.0,
        "final_score_ge_95_share": 0.0,
        "kw_raw_eq_0_share": 0.0,
        "cosine_blended_gt_0.85_share": 0.0,
        "cosine_high_kw_zero_share": 0.0,
    }
    if n_total:
        def share(pred):
            return round(sum(1 for r in log if pred(r)) / n_total, 4)

        floor_share["final_score_eq_35_share"] = share(lambda r: int(r.get("final_score") or 0) == 35)
        floor_share["final_score_lt_45_share"] = share(lambda r: float(r.get("final_score") or 0) < 45)
        floor_share["final_score_ge_95_share"] = share(lambda r: float(r.get("final_score") or 0) >= 95)
        floor_share["kw_raw_eq_0_share"] = share(lambda r: float(r.get("kw_raw") or 0) == 0.0)
        floor_share["cosine_blended_gt_0.85_share"] = share(
            lambda r: float(r.get("cosine_blended") or 0) > 0.85
        )
        floor_share["cosine_high_kw_zero_share"] = share(
            lambda r: (float(r.get("cosine_blended") or 0) > 0.85
                       and float(r.get("kw_raw") or 0) < 0.1)
        )
    (_OUT / "floor_share.json").write_text(
        json.dumps(floor_share, indent=2), encoding="utf-8"
    )

    # Optional plots
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: F401
    except ImportError:
        print("s3 done (matplotlib not available; CSV/JSON only)")
        return 0

    fig, axes = matplotlib.pyplot.subplots(3, 3, figsize=(15, 10))
    for ax, sig in zip(axes.flat, _SIGNALS):
        vals = columns[sig]
        if not vals:
            ax.set_title(f"{sig} (no data)")
            continue
        ax.hist(vals, bins=40)
        ax.set_title(f"{sig} (n={len(vals)})")
    matplotlib.pyplot.tight_layout()
    matplotlib.pyplot.savefig(_OUT / "signal_histograms.png", dpi=100)
    matplotlib.pyplot.close(fig)

    fig2 = matplotlib.pyplot.figure(figsize=(8, 5))
    matplotlib.pyplot.hist(columns["final_score"], bins=50)
    matplotlib.pyplot.title(f"final_score distribution (n={len(columns['final_score'])})")
    matplotlib.pyplot.xlabel("final_score")
    matplotlib.pyplot.ylabel("count")
    matplotlib.pyplot.tight_layout()
    matplotlib.pyplot.savefig(_OUT / "final_score_hist.png", dpi=100)
    matplotlib.pyplot.close(fig2)
    print("s3 done (with plots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
