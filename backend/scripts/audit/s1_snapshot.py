"""s1 — Snapshot live data into a frozen audit directory.

Copies backend/data/{*.jsonl, weights_active.json, weights_history/} to
backend/docs/audit/snapshot/ so all downstream audit steps read deterministic
inputs. Emits manifest.json (sha256 + row count + min/max timestamp per file)
plus a README documenting the snapshot timestamp.

Usage:
    python -m backend.scripts.audit.s1_snapshot
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
_DATA = _BACKEND / "data"
_SNAP = _BACKEND / "docs" / "audit" / "snapshot"

_JSONL_FILES = [
    "score_log.jsonl",
    "section_score_log.jsonl",
    "labels.jsonl",
    "suggestion_events.jsonl",
    "upload_events.jsonl",
    "section_deltas.jsonl",
]
_JSON_FILES = [
    "weights_active.json",
    "auto_calibrator_state.json",
    "auto_calibrator_last_attempt.json",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _jsonl_stats(path: Path) -> dict:
    n = 0
    min_ts = None
    max_ts = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("ts")
            if not ts:
                continue
            if min_ts is None or ts < min_ts:
                min_ts = ts
            if max_ts is None or ts > max_ts:
                max_ts = ts
    return {"rows": n, "min_ts": min_ts, "max_ts": max_ts}


def main() -> int:
    if not _DATA.exists():
        print(f"ERROR: {_DATA} not found")
        return 1
    _SNAP.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "source": str(_DATA),
        "files": {},
    }

    for name in _JSONL_FILES:
        src = _DATA / name
        if not src.exists():
            manifest["files"][name] = {"present": False}
            continue
        dst = _SNAP / name
        shutil.copy2(src, dst)
        stats = _jsonl_stats(dst)
        manifest["files"][name] = {
            "present": True,
            "size_bytes": dst.stat().st_size,
            "sha256": _sha256(dst),
            **stats,
        }

    for name in _JSON_FILES:
        src = _DATA / name
        if not src.exists():
            manifest["files"][name] = {"present": False}
            continue
        dst = _SNAP / name
        shutil.copy2(src, dst)
        manifest["files"][name] = {
            "present": True,
            "size_bytes": dst.stat().st_size,
            "sha256": _sha256(dst),
        }

    hist_src = _DATA / "weights_history"
    hist_dst = _SNAP / "weights_history"
    if hist_src.exists():
        if hist_dst.exists():
            shutil.rmtree(hist_dst)
        shutil.copytree(hist_src, hist_dst)
        hist_files = sorted(p.name for p in hist_dst.iterdir() if p.is_file())
        manifest["files"]["weights_history/"] = {
            "present": True,
            "count": len(hist_files),
            "files": hist_files,
        }
    else:
        manifest["files"]["weights_history/"] = {"present": False}

    (_SNAP / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    readme = (
        f"# Audit Snapshot\n\n"
        f"Captured: {manifest['snapshot_at']}\n"
        f"Source:   `{_DATA}`\n\n"
        f"All `s2..s9` scripts read exclusively from this directory.\n"
        f"Regenerate with `python -m backend.scripts.audit.s1_snapshot`.\n\n"
        f"## File counts\n\n"
    )
    rows = []
    for name, info in manifest["files"].items():
        if not info.get("present"):
            rows.append(f"- {name}: MISSING")
            continue
        if "rows" in info:
            rows.append(
                f"- {name}: {info['rows']} rows  ({info.get('min_ts', '?')} -> {info.get('max_ts', '?')})"
            )
        elif "count" in info:
            rows.append(f"- {name}: {info['count']} files")
        else:
            rows.append(f"- {name}: {info['size_bytes']} bytes")
    readme += "\n".join(rows) + "\n"
    (_SNAP / "README.md").write_text(readme, encoding="utf-8")

    print(f"snapshot written to {_SNAP}")
    for line in rows:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
