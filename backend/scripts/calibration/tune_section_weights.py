"""Grid-search per-section weights against labeled (resume, JD) pairs.

For each section (summary, experience, projects, skills) independently:
  - Joins section_score_log.jsonl with labels.jsonl on (resume_id, jd_hash)
  - Reuses the same grid as tune_weights._grid()
  - Maximizes Spearman correlation between the section's recomputed score and
    the overall label (good/ok/bad) — using overall labels as a proxy for
    section quality (no per-section labels exist yet)

This complements tune_weights.py (which tunes the global blend). Auto-calibrator
runs this after global calibration succeeds and persists the per-section
weights via weights_store.save_weights(section_weights=...).

Usage:
    python -m backend.scripts.calibration.tune_section_weights
"""
from __future__ import annotations

import json
from pathlib import Path

from .tune_weights import (
    _grid,
    _join as _join_overall,  # unused — kept import for parity
    _load_jsonl,
    _spearman,
    _kendall_tau,
    _LABEL_VALUE,
    _MIN_ROWS,
    _WEAK_SIGNAL_THRESHOLD,
)

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_DATA = _BACKEND / "data"
_SECTION_LOG = _DATA / "section_score_log.jsonl"
_LABELS = _DATA / "labels.jsonl"
_RESULTS = _DATA / "section_calibration_results.json"

_SECTIONS = ("summary", "experience", "projects", "skills")


def _join_section(section_log: list[dict], labels: list[dict], section: str) -> list[dict]:
    """Most-recent section-score event per (resume_id, jd_hash) joined with label."""
    by_key: dict[tuple[str, str], dict] = {}
    for ev in section_log:
        if ev.get("section") != section:
            continue
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
        # R4: same fallback rule as tune_weights._join — prefer ngram_coverage,
        # fall back to legacy ngram_raw and assume ngram_active=True.
        ngram_cov_raw = ev.get("ngram_coverage")
        if ngram_cov_raw is None:
            ngram_cov_raw = ev.get("ngram_raw") or 1.0
        ngram_active = bool(ev.get("ngram_active", True))
        joined.append({
            "resume_id": rid,
            "jd_hash": jdh,
            "label_value": _LABEL_VALUE[label],
            "kw_raw":        float(ev.get("kw_raw") or 0.0),
            "skill_raw":     float(ev.get("skill_raw") or 0.0),
            "ngram_coverage": float(ngram_cov_raw),
            "ngram_active":  ngram_active,
            "edu_raw":       float(ev.get("edu_raw") or 1.0),
            "seniority_raw": float(ev.get("seniority_raw") or 1.0),
            "cosine_blended":float(ev.get("cosine_blended") or 0.0),
        })
    return joined


def _evaluate_section(rows: list[dict]) -> dict:
    """Grid-search weights for one section's data.

    Returns dict with keys: status, n_rows, best, top5
    """
    if len(rows) < _MIN_ROWS:
        return {"status": "insufficient_data", "n_rows": len(rows), "best": None, "top5": []}

    labels = [r["label_value"] for r in rows]

    results: list[dict] = []
    for w_kw, w_sk, w_ng, w_edu, w_sen, w_cos in _grid():
        # R4: mirror compute_signals — redistribute w_ngram into w_kw when
        # ngram_active=False.
        scores = []
        for r in rows:
            if r["ngram_active"]:
                s = (
                    r["kw_raw"] * w_kw
                    + r["skill_raw"] * w_sk
                    + r["ngram_coverage"] * w_ng
                    + r["edu_raw"] * w_edu
                    + r["seniority_raw"] * w_sen
                    + r["cosine_blended"] * w_cos
                )
            else:
                s = (
                    r["kw_raw"] * (w_kw + w_ng)
                    + r["skill_raw"] * w_sk
                    + r["edu_raw"] * w_edu
                    + r["seniority_raw"] * w_sen
                    + r["cosine_blended"] * w_cos
                )
            scores.append(s)
        sp = _spearman(scores, labels)
        kt = _kendall_tau(scores, labels)
        results.append({
            "w_kw": w_kw, "w_skill": w_sk, "w_ngram": w_ng,
            "w_edu": w_edu, "w_sen": w_sen, "w_cos": w_cos,
            "spearman": round(sp, 4),
            "kendall_tau": round(kt, 4),
        })

    if not results:
        return {"status": "no_results", "n_rows": len(rows), "best": None, "top5": []}

    results.sort(key=lambda r: (r["spearman"], r["kendall_tau"]), reverse=True)
    best = results[0]
    status = "weak_signal" if best["spearman"] < _WEAK_SIGNAL_THRESHOLD else "ok"
    return {
        "status": status,
        "n_rows": len(rows),
        "best": best,
        "top5": results[:5],
    }


def run(
    section_log_path: Path = _SECTION_LOG,
    labels_path: Path = _LABELS,
    write_results: bool = True,
) -> dict:
    """Programmatic entrypoint. Returns {section: {status, n_rows, best, top5}}.

    Sections with insufficient data are skipped (status="insufficient_data").
    """
    section_log = _load_jsonl(section_log_path)
    labels = _load_jsonl(labels_path)

    out: dict = {}
    for section in _SECTIONS:
        rows = _join_section(section_log, labels, section)
        out[section] = _evaluate_section(rows)

    if write_results:
        try:
            _RESULTS.parent.mkdir(parents=True, exist_ok=True)
            _RESULTS.write_text(json.dumps(out, indent=2), encoding="utf-8")
        except Exception:
            pass

    return out


def main() -> int:
    out = run()
    for section, res in out.items():
        print(f"\n=== {section.upper()} ===")
        print(f"  status: {res['status']}  n_rows: {res['n_rows']}")
        if res["best"]:
            b = res["best"]
            print(f"  best: kw={b['w_kw']} skill={b['w_skill']} ngram={b['w_ngram']} "
                  f"edu={b['w_edu']} sen={b['w_sen']} cos={b['w_cos']}")
            print(f"  spearman={b['spearman']}  kendall_tau={b['kendall_tau']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
