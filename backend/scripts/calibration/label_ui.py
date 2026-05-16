"""Minimal CLI for labeling resume/JD pairs from score_log.jsonl.

Reads score_log.jsonl (newest first), skips events already labeled in
labels.jsonl, fetches the resume text from Qdrant for context, prompts the
user for good/ok/bad, appends to labels.jsonl.

Usage:
    python -m backend.scripts.calibration.label_ui
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Path setup so the script can be run as `python -m backend.scripts...`
# from repo root OR as `python label_ui.py` from inside the dir.
_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_DATA = _BACKEND / "data"
_LOG = _DATA / "score_log.jsonl"
_LABELS = _DATA / "labels.jsonl"

_VALID_LABELS = {"good", "ok", "bad"}


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


def _labeled_keys(labels: list[dict]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for lab in labels:
        rid = lab.get("resume_id") or ""
        jdh = lab.get("jd_hash") or ""
        if jdh:
            out.add((rid, jdh))
    return out


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
    log = _load_jsonl(_LOG)
    labels = _load_jsonl(_LABELS)
    already = _labeled_keys(labels)

    print(f"score_log: {len(log)} events  |  labels: {len(labels)} pairs  |  already labeled: {len(already)}")

    # Dedup events by (resume_id, jd_hash) keeping the most recent.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for ev in reversed(log):
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        if not jdh:
            continue
        key = (rid, jdh)
        if key in seen or key in already:
            continue
        seen.add(key)
        unique.append(ev)

    if not unique:
        print("nothing left to label. all events already in labels.jsonl.")
        return 0

    print(f"{len(unique)} unlabeled pair(s) remaining.\n")

    new_count = 0
    for i, ev in enumerate(unique, 1):
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        excerpt = ev.get("jd_excerpt") or "(no excerpt — old event before logging upgrade)"
        resume_text = _fetch_resume_text(rid)
        resume_excerpt = (resume_text[:800] + "…") if len(resume_text) > 800 else resume_text

        print("=" * 80)
        print(f"#{i}/{len(unique)}  resume_id={rid or '?'}  jd_hash={jdh}  score={ev.get('final_score')}")
        print(f"  kw={ev.get('kw_raw')}  skill={ev.get('skill_raw')}  cos={ev.get('cosine_blended')}  section_cos={ev.get('section_cos_raw')}")
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
        new_count += 1
        print(f"  ✓ saved as {choice}.")

    print(f"\ndone. saved {new_count} new label(s) this session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
