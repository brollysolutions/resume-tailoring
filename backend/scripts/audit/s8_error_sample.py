"""s8 — Error sample for manual annotation.

Builds a stratified 100-row CSV of "disagreement" or "anomaly" cases that a
human reviewer can open in Excel and label by failure mode. Caps rows per
resume_id at 5 so the dominant cluster cannot dominate the sheet.

Output: backend/docs/audit/error_sample/cases.csv
Stratification (≤25 rows each):
    bucket A — final_score >= 70 but label='bad'
    bucket B — final_score < 45 but label in ('good','ok')
    bucket C — score_event score in [35,41] without ceiling_hit logged
    bucket D — cosine_blended > 0.85 AND kw_raw < 0.1 (high-cos, no-kw)
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from backend.scripts.calibration.tune_weights import _join, _load_jsonl

_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]
_SNAP = _BACKEND_ROOT / "docs" / "audit" / "snapshot"
_OUT = _BACKEND_ROOT / "docs" / "audit" / "error_sample"

_BUCKET_CAP = 25
_PER_RESUME_CAP = 5


def _make_row(ev: dict, label: str | None, source: str | None, diagnosis: str) -> dict:
    return {
        "bucket": diagnosis,
        "resume_id": ev.get("resume_id", ""),
        "jd_hash": ev.get("jd_hash", ""),
        "label": label or "",
        "label_source": source or "",
        "kw_raw": round(float(ev.get("kw_raw") or 0), 4),
        "skill_raw": round(float(ev.get("skill_raw") or 0), 4),
        "ngram_raw": round(float(ev.get("ngram_raw") or 0), 4),
        "edu_raw": round(float(ev.get("edu_raw") or 0), 4),
        "seniority_raw": round(float(ev.get("seniority_raw") or 0), 4),
        "cosine_blended": round(float(ev.get("cosine_blended") or 0), 4),
        "whole_doc_cos_raw": round(float(ev.get("whole_doc_cos_raw") or 0), 4),
        "exp_cos_raw": round(float(ev.get("exp_cos_raw") or 0), 4),
        "final_score": int(float(ev.get("final_score") or 0)),
        "jd_excerpt": (ev.get("jd_excerpt", "") or "")[:200].replace("\n", " "),
        "signal_diagnosis": diagnosis,
        "failure_mode": "",
        "notes": "",
    }


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    log = _load_jsonl(_SNAP / "score_log.jsonl")
    labels = _load_jsonl(_SNAP / "labels.jsonl")
    suggest = _load_jsonl(_SNAP / "suggestion_events.jsonl")
    joined = _join(log, labels)

    label_index = {(r["resume_id"], r["jd_hash"]): r for r in joined}
    label_src_index = {(l.get("resume_id"), l.get("jd_hash")): l.get("source")
                       for l in labels}
    ceiling_index = {(s.get("resume_id"), s.get("jd_hash"))
                     for s in suggest if s.get("event") == "ceiling_hit"}

    # Match score events to labels & build buckets
    bucket_a: list[dict] = []  # high score, bad label
    bucket_b: list[dict] = []  # low score, good/ok label
    bucket_c: list[dict] = []  # floor 35-41 without ceiling_hit
    bucket_d: list[dict] = []  # high cosine, ~zero keywords

    for ev in log:
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        fs = float(ev.get("final_score") or 0)
        cos = float(ev.get("cosine_blended") or 0)
        kw = float(ev.get("kw_raw") or 0)

        joined_row = label_index.get((rid, jdh))
        label = joined_row["label"] if joined_row else None
        src = label_src_index.get((rid, jdh))

        if label == "bad" and fs >= 70:
            bucket_a.append(_make_row(ev, label, src, "high_score_bad_label"))
        if label in ("good", "ok") and fs < 45:
            bucket_b.append(_make_row(ev, label, src, "low_score_good_label"))
        if 35 <= fs <= 41 and (rid, jdh) not in ceiling_index:
            bucket_c.append(_make_row(ev, label, src, "floor_no_ceiling_reason"))
        if cos > 0.85 and kw < 0.1:
            bucket_d.append(_make_row(ev, label, src, "high_cosine_zero_kw"))

    # Apply per-resume cap and overall bucket cap; preserve order
    def _cap(rows: list[dict], cap: int) -> list[dict]:
        seen = Counter()
        out: list[dict] = []
        for r in rows:
            if seen[r["resume_id"]] >= _PER_RESUME_CAP:
                continue
            seen[r["resume_id"]] += 1
            out.append(r)
            if len(out) >= cap:
                break
        return out

    a = _cap(bucket_a, _BUCKET_CAP)
    b = _cap(bucket_b, _BUCKET_CAP)
    c = _cap(bucket_c, _BUCKET_CAP)
    d = _cap(bucket_d, _BUCKET_CAP)

    all_rows = a + b + c + d

    fields = ["bucket", "resume_id", "jd_hash", "label", "label_source",
              "kw_raw", "skill_raw", "ngram_raw", "edu_raw", "seniority_raw",
              "cosine_blended", "whole_doc_cos_raw", "exp_cos_raw",
              "final_score", "jd_excerpt", "signal_diagnosis",
              "failure_mode", "notes"]
    with (_OUT / "cases.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(all_rows)

    # Per-bucket size summary
    summary = {
        "high_score_bad_label": len(a),
        "low_score_good_label": len(b),
        "floor_no_ceiling_reason": len(c),
        "high_cosine_zero_kw": len(d),
        "total": len(all_rows),
        "raw_bucket_pool_sizes": {
            "high_score_bad_label": len(bucket_a),
            "low_score_good_label": len(bucket_b),
            "floor_no_ceiling_reason": len(bucket_c),
            "high_cosine_zero_kw": len(bucket_d),
        },
    }
    print(f"s8 done. cases.csv: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
