"""CLI for labeling resume/JD pairs from score_log.jsonl.

Reads score_log.jsonl (newest first), skips events already labeled in
labels.jsonl, fetches the resume text from Qdrant for context, prompts
user for good/ok/bad, appends to labels.jsonl.

R6 extensions:
  --per-resume-cap N   skip pairs when resume already has >= N labels (default 8)
  --stratified         sort unlabeled pairs by signal disagreement descending so
                       high-value pairs (|kw_raw - cosine_blended| > 0.4) surface first
  --from-errors PATH   prepend pairs from error_sample/cases.csv before score_log pairs;
                       defaults to backend/docs/audit/error_sample/cases.csv

Usage:
    python -m backend.scripts.calibration.label_ui
    python -m backend.scripts.calibration.label_ui --stratified --from-errors
    python -m backend.scripts.calibration.label_ui --per-resume-cap 5 --stratified
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_DATA = _BACKEND / "data"
_LOG = _DATA / "score_log.jsonl"
_LABELS = _DATA / "labels.jsonl"
_ERROR_SAMPLE = _BACKEND / "docs" / "audit" / "error_sample" / "cases.csv"

_VALID_LABELS = {"good", "ok", "bad"}
_DEFAULT_PER_RESUME_CAP = 8
_DISAGREEMENT_THRESHOLD = 0.4


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


def _load_error_csv(path: Path) -> list[dict]:
    """Load error sample CSV as list of dicts matching score_log shape."""
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rid = row.get("resume_id") or ""
            jdh = row.get("jd_hash") or ""
            if not rid or not jdh:
                continue
            rows.append({
                "resume_id": rid,
                "jd_hash": jdh,
                "jd_excerpt": row.get("jd_excerpt") or "",
                "final_score": row.get("final_score"),
                "kw_raw": _safe_float(row.get("kw_raw")),
                "skill_raw": _safe_float(row.get("skill_raw")),
                "cosine_blended": _safe_float(row.get("cosine_blended")),
                "section_weighted_cos_raw": None,
                "_from_errors": True,
            })
    return rows


def _safe_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _labeled_keys(labels: list[dict]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for lab in labels:
        rid = lab.get("resume_id") or ""
        jdh = lab.get("jd_hash") or ""
        if jdh:
            out.add((rid, jdh))
    return out


def _labels_per_resume(labels: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for lab in labels:
        rid = lab.get("resume_id") or ""
        if rid:
            counts[rid] += 1
    return counts


def _signal_disagreement(ev: dict) -> float:
    kw = _safe_float(ev.get("kw_raw")) or 0.0
    cos = _safe_float(ev.get("cosine_blended")) or 0.0
    return abs(kw - cos)


def _fetch_resume_text(resume_id: str) -> str:
    if not resume_id:
        return ""
    try:
        from app.core.vector_db import init_qdrant
        client = init_qdrant("resumes")
        results = client.retrieve(collection_name="resumes", ids=[resume_id], with_payload=True)
        if not results:
            return ""
        return (results[0].payload or {}).get("text", "") or ""
    except Exception as e:
        return f"<failed to fetch resume: {e}>"


def _append_label(record: dict) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    with _LABELS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _prompt() -> str:
    while True:
        ans = input("[g]ood / [o]k / [b]ad / [s]kip / [q]uit > ").strip().lower()
        if ans in ("g", "good"):
            return "good"
        if ans in ("o", "ok"):
            return "ok"
        if ans in ("b", "bad"):
            return "bad"
        if ans in ("s", "skip"):
            return "skip"
        if ans in ("q", "quit", "exit"):
            return "quit"
        print("  unrecognized — try g, o, b, s, or q.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Label resume/JD pairs for calibration")
    parser.add_argument(
        "--per-resume-cap", type=int, default=_DEFAULT_PER_RESUME_CAP,
        metavar="N",
        help=f"skip pairs for a resume that already has >= N labels (default {_DEFAULT_PER_RESUME_CAP})",
    )
    parser.add_argument(
        "--stratified", action="store_true",
        help="sort unlabeled pairs by |kw_raw - cosine_blended| desc (disagreement-first)",
    )
    parser.add_argument(
        "--from-errors", nargs="?", const=str(_ERROR_SAMPLE), default=None,
        metavar="PATH",
        help=f"prepend error sample CSV before score_log pairs (default: {_ERROR_SAMPLE})",
    )
    args = parser.parse_args()

    log = _load_jsonl(_LOG)
    labels = _load_jsonl(_LABELS)
    already = _labeled_keys(labels)
    resume_label_count = _labels_per_resume(labels)
    cap = args.per_resume_cap

    print(
        f"score_log: {len(log)} events  |  labels: {len(labels)} pairs  "
        f"|  already labeled: {len(already)}  |  per-resume cap: {cap}"
    )

    # Optionally prepend error sample events
    extra_events: list[dict] = []
    if args.from_errors:
        csv_path = Path(args.from_errors)
        extra_events = _load_error_csv(csv_path)
        print(f"error sample: {len(extra_events)} pairs loaded from {csv_path}")

    # Build candidate list: error sample first, then score_log (newest first)
    # Dedup by (resume_id, jd_hash), keep first occurrence.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []

    for ev in extra_events + list(reversed(log)):
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        if not jdh:
            continue
        key = (rid, jdh)
        if key in seen or key in already:
            continue
        if cap > 0 and resume_label_count.get(rid, 0) >= cap:
            continue
        seen.add(key)
        unique.append(ev)

    if args.stratified:
        unique.sort(key=_signal_disagreement, reverse=True)
        n_high = sum(1 for ev in unique if _signal_disagreement(ev) >= _DISAGREEMENT_THRESHOLD)
        print(f"stratified: {n_high}/{len(unique)} pairs have signal disagreement >= {_DISAGREEMENT_THRESHOLD}")

    if not unique:
        print("nothing left to label. all events already labeled or capped.")
        return 0

    print(f"{len(unique)} unlabeled pair(s) to review.\n")

    new_count = 0
    for i, ev in enumerate(unique, 1):
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        excerpt = ev.get("jd_excerpt") or "(no excerpt)"
        resume_text = _fetch_resume_text(rid)
        resume_excerpt = (resume_text[:800] + "…") if len(resume_text) > 800 else resume_text
        disagreement = _signal_disagreement(ev)
        source_tag = " [error-sample]" if ev.get("_from_errors") else ""

        print("=" * 80)
        print(
            f"#{i}/{len(unique)}{source_tag}  resume_id={rid or '?'}  "
            f"jd_hash={jdh}  score={ev.get('final_score')}  "
            f"disagreement={disagreement:.2f}"
        )
        sec_cos = ev.get("section_weighted_cos_raw")
        sec_cos_str = f"{sec_cos:.4f}" if sec_cos is not None else "n/a"
        print(
            f"  kw={ev.get('kw_raw')}  skill={ev.get('skill_raw')}  "
            f"cos={ev.get('cosine_blended')}  sec_weighted_cos={sec_cos_str}"
        )
        print(f"\nJD excerpt:\n  {excerpt}")
        print(f"\nResume excerpt:\n{resume_excerpt or '  (resume text unavailable)'}")
        print()

        choice = _prompt()
        if choice == "quit":
            print(f"\nsaved {new_count} new label(s). exit.")
            return 0
        if choice == "skip":
            continue

        _append_label({
            "resume_id": rid,
            "jd_hash": jdh,
            "label": choice,
        })
        resume_label_count[rid] = resume_label_count.get(rid, 0) + 1
        new_count += 1
        print(f"  ✓ saved as {choice}.")

    print(f"\ndone. saved {new_count} new label(s) this session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
