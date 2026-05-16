"""Grid-search hybrid scoring weights against labeled pairs.

Joins backend/data/score_log.jsonl with backend/data/labels.jsonl on
(resume_id, jd_hash). For each (w_kw, w_skill, w_cos) triple on the grid
(constrained to sum=1.0), recomputes the final score and measures Spearman
correlation against the manual labels (good=2, ok=1, bad=0). Prints the
top-5 triples and writes the full grid to backend/data/calibration_results.json.

Usage:
    python -m backend.scripts.calibration.tune_weights
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
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
    """Average rank with tie correction. Smallest value -> rank 1."""
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        # Find end of tie group
        while j + 1 < len(indexed) and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # ranks are 1-based
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
    """Spearman = Pearson on ranks."""
    return _pearson(_rank_avg(xs), _rank_avg(ys))


def _kendall_tau(xs: list[float], ys: list[float]) -> float:
    """Kendall tau-a (no tie correction). O(n^2) — fine for N < 1000."""
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
    """Join most-recent event per (resume_id, jd_hash) with its label."""
    # newest event wins
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
            "kw_raw": float(ev.get("kw_raw") or 0.0),
            "skill_raw": float(ev.get("skill_raw") or 0.0),
            "cosine_blended": float(ev.get("cosine_blended") or 0.0),
        })
    return joined


def _grid():
    """Yields valid (w_kw, w_skill, w_cos) triples summing to 1.0."""
    kw_range = [round(0.40 + 0.05 * i, 2) for i in range(7)]   # 0.40..0.70
    sk_range = [round(0.10 + 0.05 * i, 2) for i in range(6)]   # 0.10..0.35
    for w_kw in kw_range:
        for w_sk in sk_range:
            w_cos = round(1.0 - w_kw - w_sk, 4)
            if w_cos < 0.05 or w_cos > 0.40:
                continue
            yield (w_kw, w_sk, w_cos)


def main() -> int:
    log = _load_jsonl(_LOG)
    labels = _load_jsonl(_LABELS)
    rows = _join(log, labels)

    print(f"score_log: {len(log)} events  |  labels: {len(labels)} pairs  |  joined: {len(rows)}")

    if len(rows) < _MIN_ROWS:
        print(f"\nneed at least {_MIN_ROWS} joined rows to recommend weights. label more pairs first.")
        return 1

    label_dist = defaultdict(int)
    for r in rows:
        label_dist[r["label"]] += 1
    print(f"label distribution: {dict(label_dist)}")

    truth = [r["label_value"] for r in rows]

    results: list[dict] = []
    for w_kw, w_sk, w_cos in _grid():
        predicted = [
            w_kw * r["kw_raw"] + w_sk * r["skill_raw"] + w_cos * r["cosine_blended"]
            for r in rows
        ]
        rho = _spearman(predicted, truth)
        tau = _kendall_tau(predicted, truth)
        results.append({
            "w_kw": w_kw,
            "w_skill": w_sk,
            "w_cos": w_cos,
            "spearman": round(rho, 4),
            "kendall_tau": round(tau, 4),
        })

    results.sort(key=lambda r: r["spearman"], reverse=True)

    print(f"\ntop 5 by Spearman (N={len(rows)}):")
    print(f"  {'w_kw':>6}  {'w_skill':>8}  {'w_cos':>6}  {'spearman':>9}  {'kendall':>8}")
    for r in results[:5]:
        print(f"  {r['w_kw']:>6}  {r['w_skill']:>8}  {r['w_cos']:>6}  {r['spearman']:>9}  {r['kendall_tau']:>8}")

    best = results[0]
    print(f"\nbest: w_kw={best['w_kw']}, w_skill={best['w_skill']}, w_cos={best['w_cos']}  spearman={best['spearman']}")

    if best["spearman"] < _WEAK_SIGNAL_THRESHOLD:
        print(f"\nWARNING: best Spearman {best['spearman']} < {_WEAK_SIGNAL_THRESHOLD}. signal is weak — label more pairs before trusting this fit.")

    print("\nto apply, edit backend/app/api/match_logic/hybrid_scorer.py:")
    print(f"    raw_score = (bm25_score * {best['w_kw']}) + (skill_score * {best['w_skill']}) + (semantic_score * {best['w_cos']})")

    _DATA.mkdir(parents=True, exist_ok=True)
    _RESULTS.write_text(json.dumps({
        "n_rows": len(rows),
        "label_distribution": dict(label_dist),
        "grid": results,
    }, indent=2))
    print(f"\nfull grid written to {_RESULTS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
