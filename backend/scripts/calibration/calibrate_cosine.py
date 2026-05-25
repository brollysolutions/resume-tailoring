"""Fit the cosine remap on labeled pairs.

Current remap in hybrid_scorer.py:  (raw_cosine - 0.3) / 0.7
Assumes baseline 0.3 for unrelated docs. nomic-embed-text-v1.5 on tech text
often shows 0.5+ for unrelated pairs, so the remap underestimates the
"bad floor" and inflates bad scores.

Approach: isolate `bad`-labeled rows, take the 5th and 95th percentile of
their `whole_doc_cos_raw`. The 5th percentile becomes the new low anchor
(below this is unambiguously bad), the 95th becomes the high anchor (above
this even the worst pairs reach — anything above is informative). Remap:
    (raw - p_low) / (p_high - p_low)  clamped to [0, 1]

Usage:
    python -m backend.scripts.calibration.calibrate_cosine
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_DATA = _BACKEND / "data"
_LOG = _DATA / "score_log.jsonl"
_LABELS = _DATA / "labels.jsonl"

_MIN_BAD = 5
_MIN_GOOD = 5


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


def _join(log: list[dict], labels: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for ev in log:
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        if not jdh:
            continue
        by_key[(rid, jdh)] = ev
    out: list[dict] = []
    for lab in labels:
        rid = lab.get("resume_id") or ""
        jdh = lab.get("jd_hash") or ""
        label = lab.get("label")
        ev = by_key.get((rid, jdh))
        if ev is None or label is None:
            continue
            
        cos = ev.get("section_weighted_cos_raw")
        if cos is not None:
            cos_val = float(cos)
        else:
            whole_cos = ev.get("whole_doc_cos_raw")
            if whole_cos is None:
                continue
            whole_cos = float(whole_cos)
            
            # Check if this is a legacy log event (does not contain "p_low" anchor)
            if "p_low" not in ev:
                # Reconstruct raw cosine from old remap scale: raw = remapped * 0.7 + 0.3
                cos_val = whole_cos * 0.7 + 0.3
            else:
                cos_val = whole_cos
                
        out.append({"label": label, "cos": cos_val, "resume_id": rid, "jd_hash": jdh})
    return out


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Linear interpolation percentile. p in [0, 100]."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (p / 100.0) * (len(sorted_vals) - 1)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def run(log_path: Path = _LOG, labels_path: Path = _LABELS) -> dict:
    """Programmatic entrypoint. Returns dict with status + anchors.

    status:
      - "ok": anchors fit, p_low/p_high returned
      - "insufficient_bad": fewer than _MIN_BAD bad-labeled rows
      - "insufficient_good": fewer than _MIN_GOOD good-labeled rows
      - "narrow_spread": p_high - p_low < 0.05
    """
    log = _load_jsonl(log_path)
    labels = _load_jsonl(labels_path)
    rows = _join(log, labels)

    bad = [r for r in rows if r["label"] == "bad"]
    good = [r for r in rows if r["label"] == "good"]
    ok = [r for r in rows if r["label"] == "ok"]

    counts = {"good": len(good), "ok": len(ok), "bad": len(bad), "total": len(rows)}

    if len(bad) < _MIN_BAD:
        return {"status": "insufficient_bad", "counts": counts, "min_bad": _MIN_BAD}
    if len(good) < _MIN_GOOD:
        return {"status": "insufficient_good", "counts": counts, "min_good": _MIN_GOOD}

    bad_cos = sorted(r["cos"] for r in bad)
    good_cos = sorted(r["cos"] for r in good)
    
    # Calibrate floor on bad matches (10th percentile) and ceiling on good matches (90th percentile)
    p_low = _percentile(bad_cos, 10)
    p_high = _percentile(good_cos, 90)

    if p_high - p_low < 0.05:
        return {"status": "narrow_spread", "counts": counts, "p_low": p_low, "p_high": p_high}

    return {
        "status": "ok",
        "counts": counts,
        "p_low": round(p_low, 4),
        "p_high": round(p_high, 4),
    }


def main() -> int:
    out = run()
    c = out.get("counts", {})
    print(f"joined rows: {c.get('total', 0)}  (good={c.get('good', 0)}  ok={c.get('ok', 0)}  bad={c.get('bad', 0)})")

    if out["status"] == "insufficient_bad":
        print(f"need at least {out['min_bad']} bad-labeled rows to fit a cosine floor. label more bad pairs first.")
        return 1
    if out["status"] == "insufficient_good":
        print(f"need at least {out['min_good']} good-labeled rows to fit a cosine ceiling. label more good pairs first.")
        return 1
    if out["status"] == "narrow_spread":
        print(f"cosine spread too narrow (p_low={out['p_low']:.4f}, p_high={out['p_high']:.4f}). label more diverse pairs.")
        return 1

    p_low, p_high = out["p_low"], out["p_high"]
    print(f"\nrecommended remap anchors: p_low={p_low:.4f}  p_high={p_high:.4f}")
    print(f"new formula: (raw_cos - {p_low:.4f}) / ({p_high:.4f} - {p_low:.4f})  clamped [0, 1]")

    # Reload rows for before/after preview only (cheap).
    log = _load_jsonl(_LOG)
    labels = _load_jsonl(_LABELS)
    rows = _join(log, labels)

    def remap_old(raw: float) -> float:
        return max(0.0, (raw - 0.3) / 0.7)

    def remap_new(raw: float) -> float:
        return max(0.0, min(1.0, (raw - p_low) / (p_high - p_low)))

    print("\nbefore/after on labeled rows:")
    print(f"  {'label':>5}  {'raw':>6}  {'old':>6}  {'new':>6}")
    sample = sorted(rows, key=lambda r: r["cos"])
    for r in sample[:15]:
        print(f"  {r['label']:>5}  {r['cos']:>6.3f}  {remap_old(r['cos']):>6.3f}  {remap_new(r['cos']):>6.3f}")
    if len(sample) > 15:
        print("  ...")
        for r in sample[-5:]:
            print(f"  {r['label']:>5}  {r['cos']:>6.3f}  {remap_old(r['cos']):>6.3f}  {remap_new(r['cos']):>6.3f}")

    print("\nto apply, edit backend/app/api/match_logic/hybrid_scorer.py:")
    print(f"    # In score_resume_against_jd:")
    print(f"    whole_doc_cos = max(0.0, min(1.0, (raw - {p_low:.4f}) / ({p_high:.4f} - {p_low:.4f})))")
    print(f"    # Same substitution for the section_cos_remapped line.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
