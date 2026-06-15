"""Batch-seed score_log.jsonl by uploading a corpus of resumes and matching
each against a corpus of job descriptions.

Replaces "click through the /job-search UI 30-50 times" with one CLI run.
Uses the live backend over HTTP — same code path as a real user, so the
events end up in score_log.jsonl identically.

Inputs (defaults, override via flags):
    backend/data/calibration_corpus/resumes/   — PDF / DOCX files
    backend/data/calibration_corpus/jds/       — .txt files (one JD each)

Output: events appended to backend/data/score_log.jsonl by the backend's
existing logging path, plus a console tally.

Usage:
    # Start backend first (docker compose up  OR  uvicorn ...)
    python -m backend.scripts.calibration.seed_score_log
    python -m backend.scripts.calibration.seed_score_log --api-url http://localhost:8055
    python -m backend.scripts.calibration.seed_score_log --no-skip-existing
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("httpx is required (already a backend transitive dep). pip install httpx.")
    sys.exit(1)

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_DATA = _BACKEND / "data"
_LOG = _DATA / "score_log.jsonl"
_DEFAULT_RESUMES = _DATA / "calibration_corpus" / "resumes"
_DEFAULT_JDS = _DATA / "calibration_corpus" / "jds"

_RESUME_EXTS = {".pdf", ".docx"}
_JD_EXTS = {".txt"}


def _jd_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _existing_keys() -> set[tuple[str, str]]:
    if not _LOG.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    with _LOG.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = ev.get("resume_id") or ""
            jdh = ev.get("jd_hash") or ""
            if jdh:
                keys.add((rid, jdh))
    return keys


def _count_log_lines() -> int:
    if not _LOG.exists():
        return 0
    with _LOG.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


async def _upload_one(client: httpx.AsyncClient, path: Path) -> str | None:
    """Upload a single resume. Returns resume_id or None on failure."""
    try:
        with path.open("rb") as f:
            files = {"file": (path.name, f, "application/octet-stream")}
            resp = await client.post("/api/resume/upload", files=files, timeout=120.0)
        if resp.status_code != 200:
            print(f"  ✗ {path.name}: HTTP {resp.status_code} — {resp.text[:120]}")
            return None
        data = resp.json()
        rid = data.get("resume_id")
        if not rid:
            print(f"  ✗ {path.name}: response missing resume_id")
            return None
        print(f"  ✓ {path.name} → {rid[:8]}…")
        return rid
    except Exception as e:
        print(f"  ✗ {path.name}: {e}")
        return None


async def _match_one(
    client: httpx.AsyncClient,
    resume_id: str,
    resume_name: str,
    jd_name: str,
    jd_text: str,
    sem: asyncio.Semaphore,
    counters: dict,
) -> None:
    async with sem:
        try:
            resp = await client.post(
                "/api/match/",
                json={"resume_id": resume_id, "jd_text": jd_text},
                timeout=180.0,
            )
            if resp.status_code != 200:
                print(f"  ✗ {resume_name} × {jd_name}: HTTP {resp.status_code}")
                counters["failed"] += 1
                return
            data = resp.json()
            score = data.get("score", "?")
            print(f"  ✓ {resume_name} × {jd_name}: score={score}")
            counters["gained"] += 1
        except Exception as e:
            print(f"  ✗ {resume_name} × {jd_name}: {e}")
            counters["failed"] += 1


async def run(args: argparse.Namespace) -> int:
    resumes_dir = Path(args.resumes_dir)
    jds_dir = Path(args.jds_dir)

    if not resumes_dir.is_dir():
        print(f"resumes dir not found: {resumes_dir}")
        return 1
    if not jds_dir.is_dir():
        print(f"jds dir not found: {jds_dir}")
        return 1

    resume_files = sorted(
        p for p in resumes_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _RESUME_EXTS
    )
    jd_files = sorted(
        p for p in jds_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _JD_EXTS
    )

    if not resume_files:
        print(f"no PDF/DOCX files in {resumes_dir}")
        return 1
    if not jd_files:
        print(f"no .txt files in {jds_dir}")
        return 1

    jds: list[tuple[str, str, str]] = []
    for p in jd_files:
        try:
            text = p.read_text(encoding="utf-8").strip()
        except Exception as e:
            print(f"  ✗ {p.name}: read failed {e}")
            continue
        if not text:
            continue
        jds.append((p.stem, _jd_hash(text), text))

    print(f"\nresumes: {len(resume_files)}  jds: {len(jds)}  → {len(resume_files) * len(jds)} max pairs")
    print(f"api: {args.api_url}\n")

    before_count = _count_log_lines()
    existing = _existing_keys() if args.skip_existing else set()
    if args.skip_existing:
        print(f"dedup: {len(existing)} existing (resume_id, jd_hash) pairs will be skipped after matching\n")

    async with httpx.AsyncClient(base_url=args.api_url) as client:
        # Health check
        try:
            health = await client.get("/", timeout=10.0)
            if health.status_code >= 500:
                print(f"backend unhealthy: {health.status_code}")
                return 1
        except Exception as e:
            print(f"backend unreachable at {args.api_url}: {e}")
            return 1

        # Upload resumes
        print("uploading resumes:")
        resume_ids: dict[str, str] = {}  # resume_name -> resume_id
        for p in resume_files:
            rid = await _upload_one(client, p)
            if rid is None:
                print(f"\nupload failed for {p.name}. aborting (matching would be meaningless).")
                return 1
            resume_ids[p.stem] = rid

        # Build pair list, applying dedup
        sem = asyncio.Semaphore(max(1, args.concurrency))
        counters = {"gained": 0, "failed": 0, "skipped": 0}
        tasks = []
        print("\nmatching:")
        for resume_name, rid in resume_ids.items():
            for jd_name, jdh, jd_text in jds:
                if args.skip_existing and (rid, jdh) in existing:
                    counters["skipped"] += 1
                    continue
                tasks.append(_match_one(client, rid, resume_name, jd_name, jd_text, sem, counters))

        if not tasks:
            print("  nothing to do (all pairs already in log).")
        else:
            await asyncio.gather(*tasks)

    after_count = _count_log_lines()
    print(f"\nlog: before={before_count}  after={after_count}  gained={counters['gained']}  skipped={counters['skipped']}  failed={counters['failed']}")
    return 0 if counters["failed"] == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-seed score_log.jsonl from a resumes + JDs corpus.")
    parser.add_argument("--api-url", default="http://localhost:8055")
    parser.add_argument("--resumes-dir", default=str(_DEFAULT_RESUMES))
    parser.add_argument("--jds-dir", default=str(_DEFAULT_JDS))
    parser.add_argument("--concurrency", type=int, default=4, help="max parallel /api/match/ calls")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="skip (resume_id, jd_hash) pairs already in score_log.jsonl (default)")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false",
                        help="re-match even if the pair already exists in the log")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
