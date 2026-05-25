"""s5 — Calibration stability replay.

For each weights_history snapshot, re-score the CURRENT snapshot/joined-rows
and report Spearman. Detects whether past weight sets would outperform the
active one on the latest labels, and whether the calibrator is producing
materially different weights or drifting in noise.

Outputs under backend/docs/audit/calibration/:
    weights_timeline.csv  — one row per historical snapshot
    replay_table.csv      — per snapshot: rho/tau on current joined rows
    baseline_comparison.json — {defaults, active, top-grid, equal-1/6}
    grid_topology.png     — only if matplotlib (optional)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from backend.scripts.calibration.tune_weights import (
    _join,
    _kendall_tau,
    _load_jsonl,
    _spearman,
    run as tune_weights_run,
)

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_SNAP = _BACKEND / "docs" / "audit" / "snapshot"
_OUT = _BACKEND / "docs" / "audit" / "calibration"

_WEIGHT_KEYS = ["w_kw", "w_skill", "w_ngram", "w_edu", "w_sen", "w_cos"]

# Baked-in defaults from weights_store.DEFAULTS (mirror — read-only audit)
_DEFAULTS = {
    "w_kw": 0.30,
    "w_skill": 0.20,
    "w_ngram": 0.10,
    "w_edu": 0.05,
    "w_sen": 0.10,
    "w_cos": 0.25,
}


def _score(rows, w):
    return [
        w["w_kw"] * r["kw_raw"]
        + w["w_skill"] * r["skill_raw"]
        + w["w_ngram"] * r["ngram_raw"]
        + w["w_edu"] * r["edu_raw"]
        + w["w_sen"] * r["seniority_raw"]
        + w["w_cos"] * r["cosine_blended"]
        for r in rows
    ]


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    log = _load_jsonl(_SNAP / "score_log.jsonl")
    labels = _load_jsonl(_SNAP / "labels.jsonl")
    joined = _join(log, labels)
    if not joined:
        print("s5: no joined rows; abort")
        return 1
    truth = [r["label_value"] for r in joined]
    weights_active = json.loads((_SNAP / "weights_active.json").read_text())

    # --- weights_timeline.csv + replay_table.csv ---
    hist_dir = _SNAP / "weights_history"
    history_files = sorted(hist_dir.glob("*.json")) if hist_dir.exists() else []

    timeline_rows = []
    replay_rows = []

    # add the active weights as the "current" row first
    timeline_rows.append({
        "snapshot": "weights_active.json",
        "calibrated_at": weights_active.get("calibrated_at", ""),
        "source": weights_active.get("source", ""),
        "n_rows": weights_active.get("n_rows", ""),
        "reported_spearman": weights_active.get("spearman", ""),
        **{k: weights_active.get(k, "") for k in _WEIGHT_KEYS},
    })

    pred_active = _score(joined, weights_active)
    replay_rows.append({
        "snapshot": "weights_active.json",
        "calibrated_at": weights_active.get("calibrated_at", ""),
        "rho_on_snapshot": round(_spearman(pred_active, truth), 4),
        "tau_on_snapshot": round(_kendall_tau(pred_active, truth), 4),
        "n_joined": len(joined),
    })

    for f in history_files:
        try:
            w = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        timeline_rows.append({
            "snapshot": f.name,
            "calibrated_at": w.get("calibrated_at", ""),
            "source": w.get("source", ""),
            "n_rows": w.get("n_rows", ""),
            "reported_spearman": w.get("spearman", ""),
            **{k: w.get(k, "") for k in _WEIGHT_KEYS},
        })
        pred = _score(joined, w)
        replay_rows.append({
            "snapshot": f.name,
            "calibrated_at": w.get("calibrated_at", ""),
            "rho_on_snapshot": round(_spearman(pred, truth), 4),
            "tau_on_snapshot": round(_kendall_tau(pred, truth), 4),
            "n_joined": len(joined),
        })

    with (_OUT / "weights_timeline.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(timeline_rows[0].keys()))
        wr.writeheader()
        wr.writerows(timeline_rows)

    with (_OUT / "replay_table.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(replay_rows[0].keys()))
        wr.writeheader()
        wr.writerows(replay_rows)

    # --- baseline_comparison.json: re-run grid on snapshot data ---
    grid_result = tune_weights_run(
        log_path=_SNAP / "score_log.jsonl",
        labels_path=_SNAP / "labels.jsonl",
        write_results=False,
    )
    top_grid = grid_result.get("best") or {}

    pred_defaults = _score(joined, _DEFAULTS)
    rho_defaults = _spearman(pred_defaults, truth)

    equal_w = {k: 1/6 for k in _WEIGHT_KEYS}
    pred_eq = _score(joined, equal_w)
    rho_eq = _spearman(pred_eq, truth)

    baseline = {
        "n_joined_snapshot": len(joined),
        "active_rho_on_snapshot": round(_spearman(pred_active, truth), 4),
        "defaults_rho_on_snapshot": round(rho_defaults, 4),
        "equal_weight_baseline_rho": round(rho_eq, 4),
        "top_grid_on_snapshot_rho": top_grid.get("spearman"),
        "top_grid_weights": {k: top_grid.get(k) for k in _WEIGHT_KEYS},
        "grid_status": grid_result.get("status"),
        "grid_label_distribution": grid_result.get("label_distribution"),
        "defaults_used_for_baseline": _DEFAULTS,
    }
    (_OUT / "baseline_comparison.json").write_text(
        json.dumps(baseline, indent=2), encoding="utf-8"
    )

    # --- optional grid topology plot ---
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        plt = None
    if plt is not None and "grid" in grid_result:
        grid_pts = grid_result["grid"]
        fig = plt.figure(figsize=(9, 6))
        xs = [p["w_cos"] for p in grid_pts]
        ys = [p["spearman"] for p in grid_pts]
        cs = [p["w_kw"] for p in grid_pts]
        sc = plt.scatter(xs, ys, c=cs, cmap="viridis", s=12, alpha=0.7)
        plt.colorbar(sc, label="w_kw")
        plt.xlabel("w_cos")
        plt.ylabel("Spearman ρ")
        plt.title(f"Grid topology (n={len(grid_pts)} points, best ρ={baseline['top_grid_on_snapshot_rho']})")
        plt.tight_layout()
        plt.savefig(_OUT / "grid_topology.png", dpi=100)
        plt.close(fig)

    print(f"s5 done. active_rho={baseline['active_rho_on_snapshot']} "
          f"defaults_rho={baseline['defaults_rho_on_snapshot']} "
          f"top_grid_rho={baseline['top_grid_on_snapshot_rho']} "
          f"equal_rho={baseline['equal_weight_baseline_rho']}")
    for row in replay_rows:
        print(f"  {row['snapshot']:60s} rho={row['rho_on_snapshot']}")
    print(f"  top grid weights: {baseline['top_grid_weights']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
