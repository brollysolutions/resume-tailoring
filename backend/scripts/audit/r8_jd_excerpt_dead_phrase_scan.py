"""r8 — Augment dead-phrase classification with score_log jd_excerpts.

The corpus-only scan in s6 only sees 12 JDs + 8 resumes. Before pruning
phrases from `_NGRAM_SKILLS`, confirm each candidate is also absent across
the 137 unique `jd_excerpt` strings in `backend/docs/audit/snapshot/score_log.jsonl`.

Inputs:
    backend/docs/audit/snapshot/score_log.jsonl
    backend/docs/audit/keywords/ngram_phrase_hits.csv (corpus-only baseline)

Output:
    backend/docs/audit/keywords/ngram_dead_after_excerpts.csv
        phrase, jd_corpus_hits, resume_corpus_hits, jd_excerpt_hits, dead_in_all_three

Usage:
    python -m backend.scripts.audit.r8_jd_excerpt_dead_phrase_scan
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_ROOT = _HERE.parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.keyword_utils import _NGRAM_SKILLS  # noqa: E402

_SNAP = _BACKEND_ROOT / "docs" / "audit" / "snapshot"
_KW_DIR = _BACKEND_ROOT / "docs" / "audit" / "keywords"
_BASELINE = _KW_DIR / "ngram_phrase_hits.csv"
_OUT = _KW_DIR / "ngram_dead_after_excerpts.csv"


def main() -> int:
    log_path = _SNAP / "score_log.jsonl"
    if not log_path.exists():
        print(f"missing {log_path} — run s1_snapshot first")
        return 1
    if not _BASELINE.exists():
        print(f"missing {_BASELINE} — run s6_keyword_diagnostic first")
        return 1

    baseline: dict[str, dict[str, int]] = {}
    with _BASELINE.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            baseline[row["phrase"]] = {
                "jd_corpus_hits": int(row.get("jd_hits") or 0),
                "resume_corpus_hits": int(row.get("resume_hits") or 0),
            }

    # Dedup by jd_hash, prefer the longest excerpt seen for that hash
    excerpts: dict[str, str] = {}
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            jdh = row.get("jd_hash")
            text = row.get("jd_excerpt") or ""
            if not jdh:
                continue
            prev = excerpts.get(jdh, "")
            if len(text) > len(prev):
                excerpts[jdh] = text

    excerpt_hit_counts: dict[str, int] = {p: 0 for p in _NGRAM_SKILLS}
    for jdh, text in excerpts.items():
        lower = text.lower()
        for phrase in _NGRAM_SKILLS:
            if phrase in lower:
                excerpt_hit_counts[phrase] += 1

    rows = []
    for phrase in sorted(_NGRAM_SKILLS):
        base = baseline.get(phrase, {"jd_corpus_hits": 0, "resume_corpus_hits": 0})
        jd_h = base["jd_corpus_hits"]
        rs_h = base["resume_corpus_hits"]
        ex_h = excerpt_hit_counts[phrase]
        dead_all = (jd_h == 0 and rs_h == 0 and ex_h == 0)
        rows.append({
            "phrase": phrase,
            "jd_corpus_hits": jd_h,
            "resume_corpus_hits": rs_h,
            "jd_excerpt_hits": ex_h,
            "dead_in_all_three": dead_all,
        })

    _KW_DIR.mkdir(parents=True, exist_ok=True)
    with _OUT.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["phrase", "jd_corpus_hits",
                                           "resume_corpus_hits",
                                           "jd_excerpt_hits",
                                           "dead_in_all_three"])
        wr.writeheader()
        wr.writerows(rows)

    dead = [r["phrase"] for r in rows if r["dead_in_all_three"]]
    revived = [r["phrase"] for r in rows
               if r["jd_corpus_hits"] == 0 and r["resume_corpus_hits"] == 0
               and r["jd_excerpt_hits"] > 0]
    print(f"unique jd_excerpts scanned: {len(excerpts)}")
    print(f"phrases dead in ALL THREE corpora: {len(dead)} of {len(_NGRAM_SKILLS)}")
    print(f"phrases revived by excerpt scan (corpus said dead, excerpts say live): {len(revived)}")
    if revived:
        print("  revived examples:", ", ".join(revived[:10]))
    print("\ndead-in-all-three (safe to prune):")
    for p in dead:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
