"""s7 — Ceiling and seniority audit.

For each unique jd_hash in the snapshot, run parse_jd_hard_requirements on the
logged jd_excerpt (prefer full-text JD from calibration_corpus when available)
and report extracted hard requirements alongside how often that pair was
ceiling-floored.

Outputs under backend/docs/audit/ceiling/:
    hard_req_extraction.csv
    cosine_remap_anomalies.csv
    floor_clustering.json
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.api.match_logic.ceiling_detector import parse_jd_hard_requirements  # noqa: E402

from backend.scripts.calibration.tune_weights import _load_jsonl  # noqa: E402

_SNAP = _BACKEND_ROOT / "docs" / "audit" / "snapshot"
_CORPUS = _BACKEND_ROOT / "data" / "calibration_corpus" / "jds"
_OUT = _BACKEND_ROOT / "docs" / "audit" / "ceiling"


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    log = _load_jsonl(_SNAP / "score_log.jsonl")
    suggest = _load_jsonl(_SNAP / "suggestion_events.jsonl")

    # Group score_log by jd_hash; capture excerpt + all final_scores
    by_jd: dict[str, dict] = defaultdict(lambda: {
        "excerpt": "", "events": [], "ceiling_hits": 0
    })
    for ev in log:
        jdh = ev.get("jd_hash")
        if not jdh:
            continue
        slot = by_jd[jdh]
        if ev.get("jd_excerpt"):
            slot["excerpt"] = ev["jd_excerpt"]
        slot["events"].append(ev)

    for ev in suggest:
        if ev.get("event") != "ceiling_hit":
            continue
        jdh = ev.get("jd_hash")
        if jdh in by_jd:
            by_jd[jdh]["ceiling_hits"] += 1

    # --- hard_req_extraction.csv ---
    rows = []
    floor_per_pair = Counter()  # for floor_clustering.json
    for jdh, slot in by_jd.items():
        text = slot["excerpt"]
        text_full = ""
        # Best-effort full-text from corpus by excerpt prefix match
        prefix = text[:60].strip().lower()
        if prefix:
            for f in _CORPUS.glob("*.txt"):
                full = f.read_text(encoding="utf-8", errors="ignore")
                if full[:200].lower().find(prefix) >= 0:
                    text_full = full
                    break
        used_text = text_full if text_full else text
        used_source = "corpus_full" if text_full else "excerpt_240"

        req = parse_jd_hard_requirements(used_text)
        n_events = len(slot["events"])
        scores = [int(e.get("final_score") or 0) for e in slot["events"]]
        rows.append({
            "jd_hash": jdh,
            "n_score_events": n_events,
            "ceiling_hit_events": slot["ceiling_hits"],
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "extracted_years": req["min_years_experience"] or "",
            "extracted_degrees": "|".join(req["required_degrees"]),
            "extracted_seniority": req["seniority_level"] or "",
            "source": used_source,
            "excerpt_first_120": (used_text[:120] or "").replace("\n", " "),
        })
        for s in scores:
            floor_per_pair[(jdh, s == 35)] += 1
    rows.sort(key=lambda r: r["n_score_events"], reverse=True)
    with (_OUT / "hard_req_extraction.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)

    # --- cosine_remap_anomalies.csv ---
    anomalies = []
    for ev in log:
        cos = float(ev.get("cosine_blended") or 0)
        kw = float(ev.get("kw_raw") or 0)
        fs = float(ev.get("final_score") or 0)
        if cos > 0.85 and kw < 0.1 and fs >= 35:
            anomalies.append({
                "ts": ev.get("ts"),
                "resume_id": ev.get("resume_id"),
                "jd_hash": ev.get("jd_hash"),
                "kw_raw": round(kw, 4),
                "skill_raw": round(float(ev.get("skill_raw") or 0), 4),
                "ngram_raw": round(float(ev.get("ngram_raw") or 0), 4),
                "cosine_blended": round(cos, 4),
                "whole_doc_cos_raw": round(float(ev.get("whole_doc_cos_raw") or 0), 4),
                "exp_cos_raw": round(float(ev.get("exp_cos_raw") or 0), 4),
                "final_score": int(fs),
                "jd_excerpt_60": (ev.get("jd_excerpt", "") or "")[:60].replace("\n", " "),
            })
    anomalies.sort(key=lambda r: r["cosine_blended"], reverse=True)
    with (_OUT / "cosine_remap_anomalies.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(anomalies[0].keys()) if anomalies else
                            ["ts", "resume_id", "jd_hash", "kw_raw", "skill_raw",
                             "ngram_raw", "cosine_blended", "whole_doc_cos_raw",
                             "exp_cos_raw", "final_score", "jd_excerpt_60"])
        wr.writeheader()
        wr.writerows(anomalies)

    # --- floor_clustering.json ---
    floor_counts = Counter()
    score_buckets = Counter()
    extracted_summary = Counter()
    for ev in log:
        fs = int(ev.get("final_score") or 0)
        score_buckets[(fs // 5) * 5] += 1
        if fs <= 35:
            floor_counts["<=35"] += 1
        elif fs <= 41:
            floor_counts["36-41"] += 1
        elif fs <= 50:
            floor_counts["42-50"] += 1
        elif fs <= 65:
            floor_counts["51-65"] += 1
        else:
            floor_counts[">65"] += 1
    for r in rows:
        key = (
            "yrs=" + str(r["extracted_years"] or "?"),
            "deg=" + (r["extracted_degrees"] or "?"),
            "sen=" + (r["extracted_seniority"] or "?"),
        )
        extracted_summary[" / ".join(key)] += 1

    floor_clustering = {
        "n_events_total": sum(score_buckets.values()),
        "buckets_by_final_score_step5": dict(sorted(score_buckets.items())),
        "floor_buckets": dict(floor_counts),
        "n_jd_unique": len(by_jd),
        "n_jd_with_extracted_year": sum(1 for r in rows if r["extracted_years"]),
        "n_jd_with_extracted_degree": sum(1 for r in rows if r["extracted_degrees"]),
        "n_jd_with_extracted_seniority": sum(1 for r in rows if r["extracted_seniority"]),
        "extraction_combos_top10": dict(extracted_summary.most_common(10)),
        "n_anomalies_high_cosine_zero_kw": len(anomalies),
    }
    (_OUT / "floor_clustering.json").write_text(
        json.dumps(floor_clustering, indent=2), encoding="utf-8"
    )

    print(f"s7 done. JDs={len(rows)} anomalies(highcos+nokw)={len(anomalies)} "
          f"jd_with_year={floor_clustering['n_jd_with_extracted_year']}/{len(rows)} "
          f"jd_with_degree={floor_clustering['n_jd_with_extracted_degree']}/{len(rows)} "
          f"jd_with_seniority={floor_clustering['n_jd_with_extracted_seniority']}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
