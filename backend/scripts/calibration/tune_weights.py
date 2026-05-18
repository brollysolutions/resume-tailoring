"""Grid-search hybrid scoring weights against labeled pairs.

Joins backend/data/score_log.jsonl with backend/data/labels.jsonl on
(resume_id, jd_hash). For each 6-tuple (w_kw, w_skill, w_ngram, w_edu,
w_sen, w_cos) on the grid (constrained to sum=1.0), recomputes the final
score and measures Spearman correlation against labels (good=2, ok=1, bad=0).
Prints top-5 and writes full grid to backend/data/calibration_results.json.

Usage:
    python -m backend.scripts.calibration.tune_weights
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from itertools import product
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_DATA = _BACKEND / "data"
_LOG = _DATA / "score_log.jsonl"
_LABELS = _DATA / "labels.jsonl"
_RESULTS = _DATA / "calibration_results.json"

_LABEL_VALUE = {"good": 2, "ok": 1, "bad": 0}
_MIN_ROWS = 10
_WEAK_SIGNAL_THRESHOLD = 0.3


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _rank_avg(values: list[float]) -> list[float]:
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = sum((xs[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ys[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_rank_avg(xs), _rank_avg(ys))


def _kendall_tau(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[i] - xs[j]
            dy = ys[i] - ys[j]
            if dx == 0 or dy == 0:
                continue
            if (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return (concordant - discordant) / total if total else 0.0


def _join(log: list[dict], labels: list[dict]) -> list[dict]:
    """Join most-recent score event per (resume_id, jd_hash) with its label."""
    by_key: dict[tuple[str, str], dict] = {}
    for ev in log:
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        if not jdh:
            continue
        by_key[(rid, jdh)] = ev

    joined: list[dict] = []
    for lab in labels:
        rid = lab.get("resume_id") or ""
        jdh = lab.get("jd_hash") or ""
        label = lab.get("label")
        if label not in _LABEL_VALUE:
            continue
        ev = by_key.get((rid, jdh))
        if ev is None:
            continue
        joined.append({
            "resume_id": rid,
            "jd_hash": jdh,
            "label": label,
            "label_value": _LABEL_VALUE[label],
            "kw_raw":        float(ev.get("kw_raw") or 0.0),
            "skill_raw":     float(ev.get("skill_raw") or 0.0),
            "ngram_raw":     float(ev.get("ngram_raw") or 1.0),   # 1.0 = no penalty for old events
            "edu_raw":       float(ev.get("edu_raw") or 1.0),
            "seniority_raw": float(ev.get("seniority_raw") or 1.0),
            "cosine_blended":float(ev.get("cosine_blended") or 0.0),
        })
    return joined


def _grid():
    """Yield 6-tuples (w_kw, w_skill, w_ngram, w_edu, w_sen, w_cos) summing to 1.0.

    Grid ranges (step 0.05 each):
        w_kw:   0.20 – 0.40  (5 values)
        w_skill:0.10 – 0.25  (4 values)
        w_ngram:0.05 – 0.20  (4 values)
        w_edu:  0.00, 0.05, 0.10 (3 values)
        w_sen:  0.05, 0.10, 0.15 (3 values)
        w_cos:  remainder, accepted if 0.10 – 0.45
    Total: 5×4×4×3×3 = 720 candidate points.
    """
    kw_vals    = [round(0.20 + 0.05 * i, 2) for i in range(5)]
    skill_vals = [round(0.10 + 0.05 * i, 2) for i in range(4)]
    ngram_vals = [round(0.05 + 0.05 * i, 2) for i in range(4)]
    edu_vals   = [0.00, 0.05, 0.10]
    sen_vals   = [0.05, 0.10, 0.15]

    for w_kw, w_sk, w_ng, w_edu, w_sen in product(
        kw_vals, skill_vals, ngram_vals, edu_vals, sen_vals
    ):
        w_cos = round(1.0 - w_kw - w_sk - w_ng - w_edu - w_sen, 4)
        if 0.10 <= w_cos <= 0.45:
            yield (w_kw, w_sk, w_ng, w_edu, w_sen, w_cos)


def run(log_path: Path = _LOG, labels_path: Path = _LABELS, write_results: bool = True) -> dict:
    """Programmatic entrypoint used by auto_calibrator.

    Returns dict with keys: status, n_log, n_labels, n_rows, best, top5, grid.
    status: "ok" | "weak_signal" | "insufficient_data"
    """
    log = _load_jsonl(log_path)
    labels = _load_jsonl(labels_path)
    rows = _join(log, labels)

    if len(rows) < _MIN_ROWS:
        return {
            "status": "insufficient_data",
            "n_log": len(log),
            "n_labels": len(labels),
            "n_rows": len(rows),
            "min_rows": _MIN_ROWS,
        }

    label_dist = defaultdict(int)
    for r in rows:
        label_dist[r["label"]] += 1

    truth = [r["label_value"] for r in rows]
    results: list[dict] = []

    for w_kw, w_sk, w_ng, w_edu, w_sen, w_cos in _grid():
        predicted = [
            w_kw * r["kw_raw"]
            + w_sk  * r["skill_raw"]
            + w_ng  * r["ngram_raw"]
            + w_edu * r["edu_raw"]
            + w_sen * r["seniority_raw"]
            + w_cos * r["cosine_blended"]
            for r in rows
        ]
        rho = _spearman(predicted, truth)
        tau = _kendall_tau(predicted, truth)
        results.append({
            "w_kw": w_kw,
            "w_skill": w_sk,
            "w_ngram": w_ng,
            "w_edu": w_edu,
            "w_sen": w_sen,
            "w_cos": w_cos,
            "spearman": round(rho, 4),
            "kendall_tau": round(tau, 4),
        })

    results.sort(key=lambda r: r["spearman"], reverse=True)
    best = results[0]

    if write_results:
        _DATA.mkdir(parents=True, exist_ok=True)
        _RESULTS.write_text(json.dumps({
            "n_rows": len(rows),
            "label_distribution": dict(label_dist),
            "grid": results,
        }, indent=2))

    status = "ok" if best["spearman"] >= _WEAK_SIGNAL_THRESHOLD else "weak_signal"
    return {
        "status": status,
        "n_log": len(log),
        "n_labels": len(labels),
        "n_rows": len(rows),
        "label_distribution": dict(label_dist),
        "best": best,
        "top5": results[:5],
        "grid": results,
        "weak_signal_threshold": _WEAK_SIGNAL_THRESHOLD,
    }


def main() -> int:
    out = run()
    print(f"score_log: {out.get('n_log', 0)} events  |  labels: {out.get('n_labels', 0)} pairs  |  joined: {out.get('n_rows', 0)}")

    if out["status"] == "insufficient_data":
        print(f"\nneed at least {out['min_rows']} joined rows to recommend weights. label more pairs first.")
        return 1

    print(f"label distribution: {out['label_distribution']}")
    print(f"\ntop 5 by Spearman (N={out['n_rows']}):")
    print(f"  {'w_kw':>6}  {'w_skill':>7}  {'w_ngram':>7}  {'w_edu':>6}  {'w_sen':>6}  {'w_cos':>6}  {'spearman':>9}  {'kendall':>8}")
    for r in out["top5"]:
        print(
            f"  {r['w_kw']:>6}  {r['w_skill']:>7}  {r['w_ngram']:>7}  "
            f"{r['w_edu']:>6}  {r['w_sen']:>6}  {r['w_cos']:>6}  "
            f"{r['spearman']:>9}  {r['kendall_tau']:>8}"
        )

    best = out["best"]
    print(
        f"\nbest: w_kw={best['w_kw']} w_skill={best['w_skill']} w_ngram={best['w_ngram']} "
        f"w_edu={best['w_edu']} w_sen={best['w_sen']} w_cos={best['w_cos']}  "
        f"spearman={best['spearman']}"
    )

    if out["status"] == "weak_signal":
        print(f"\nWARNING: best Spearman {best['spearman']} < {out['weak_signal_threshold']}. label more pairs.")

    print("\nto apply: POST /api/admin/calibration/run or wait for auto-calibrator.")
    print(f"\nfull grid written to {_RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
