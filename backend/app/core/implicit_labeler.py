"""Derive `labels.jsonl` rows from match-phase user decisions.

Reads `data/score_log.jsonl` (written by hybrid_scorer.py on every match) and
`data/suggestion_events.jsonl` (written by tailor.py on tailor click).

Heuristic:
    If (resume_id, jd_hash) in score_log AND in suggestions_events → "good"
    (user matched + clicked Tailor = found match relevant)

    If (resume_id, jd_hash) in score_log ONLY AND score_ts > 2 hours old → "bad"
    (user matched but never tailored after waiting period = irrelevant)

    Otherwise → skip (not enough signal yet)

Avoids the post-tailoring bias of the old heuristic. Signals come from the
match phase only, before user contamination through suggestions.

Dedupes against existing rows in `labels.jsonl` (by resume_id + jd_hash) so
re-running is safe and incremental.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKEND = Path(__file__).resolve().parents[2]
_DATA = _BACKEND / "data"
_EVENTS = _DATA / "suggestion_events.jsonl"
_LABELS = _DATA / "labels.jsonl"
_SCORE_LOG = _DATA / "score_log.jsonl"

BAD_LABEL_DELAY_HOURS = 2
FAST_CLICK_SEC = 120  # < 2min = strong "good" signal
SESSION_WINDOW_MIN = 30  # group matches within 30min as one session
QUICK_ABANDON_MIN = 20   # low-score + no tailor after this → "bad" without waiting 2h
LOW_SCORE_THRESHOLD = 40 # final_score below this is clearly bad


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


def log_suggestion_event(
    event: str,
    resume_id: str,
    jd_hash: str,
    **extra,
) -> None:
    """Best-effort append. Never raises."""
    if os.environ.get("TESTING") == "1":
        return
    if not resume_id or not jd_hash:
        return
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "resume_id": resume_id,
            "jd_hash": jd_hash,
            **extra,
        }
        with _EVENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception as e:
        logger.debug("suggestion_events log write failed: %s", e)


def derive_labels() -> dict:
    """Multi-signal label derivation from match-phase data only.

    Signals:
    1. Tailor-click: (resume, jd) in suggestions_events → "good" (or "ok" if slow click)
    2. No-tailor timeout: (resume, jd) in score_log but not suggestions → "bad" if old enough
    3. Ceiling hit: explicit event → "bad" (highest confidence)
    4. Session pairwise: resume matched multiple JDs in same session, tailored some → refine labels

    Returns: {new_labels, skipped_existing, skipped_too_recent, by_signal: {...}}
    """
    from datetime import timedelta

    # Load all data sources
    score_log = _load_jsonl(_SCORE_LOG)
    events = _load_jsonl(_EVENTS)
    existing_labels = {(l["resume_id"], l["jd_hash"]) for l in _load_jsonl(_LABELS)}

    if not score_log:
        return {
            "new_labels": 0,
            "skipped_existing": 0,
            "skipped_too_recent": 0,
            "by_signal": {"tailor_clicked": 0, "no_tailor_2h": 0, "ceiling_hit": 0, "session_pairwise": 0, "quick_abandon": 0},
        }

    # Build indices from events
    suggestions_ts: dict[tuple[str, str], str] = {}  # (rid, jdh) → ts of suggestions_generated
    ceiling_bad: set[tuple[str, str]] = set()  # (rid, jdh) with ceiling_hit event
    for ev in events:
        rid = ev.get("resume_id") or ""
        jdh = ev.get("jd_hash") or ""
        if not rid or not jdh:
            continue
        key = (rid, jdh)
        et = ev.get("event")
        if et == "suggestions_generated":
            suggestions_ts[key] = ev.get("ts", "")
        elif et == "ceiling_hit":
            ceiling_bad.add(key)

    # Build session index: group score_log by (resume_id, 30-min bucket) → list of jd_hashes
    sessions: dict[tuple[str, str], list[tuple[str, str]]] = {}  # (rid, time_bucket) → [(jdh, ts), ...]
    for row in score_log:
        rid = row.get("resume_id") or ""
        jdh = row.get("jd_hash") or ""
        ts_str = row.get("ts", "")
        if not rid or not jdh or not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            bucket = (ts.hour * 2 + ts.minute // 30)  # 30-min bucket of day
            session_key = (rid, str(ts.date()) + f"_{bucket}")
        except (ValueError, AttributeError):
            continue
        if session_key not in sessions:
            sessions[session_key] = []
        sessions[session_key].append((jdh, ts_str))

    # Generate labels: first pass — individual signals
    labels_to_write: dict[tuple[str, str], dict] = {}  # (rid, jdh) → label_dict
    now = datetime.now(timezone.utc)
    signal_counts = {"tailor_clicked": 0, "no_tailor_2h": 0, "ceiling_hit": 0, "session_pairwise": 0, "quick_abandon": 0}

    for row in score_log:
        rid = row.get("resume_id") or ""
        jdh = row.get("jd_hash") or ""
        ts_str = row.get("ts", "")
        if not rid or not jdh:
            continue
        key = (rid, jdh)

        # Skip if already labeled
        if key in existing_labels:
            continue
        if key in labels_to_write:
            continue

        # Signal 5: Ceiling hit (highest confidence bad)
        if key in ceiling_bad:
            labels_to_write[key] = {
                "resume_id": rid,
                "jd_hash": jdh,
                "label": "bad",
                "source": "implicit",
                "signal": "ceiling_hit",
            }
            signal_counts["ceiling_hit"] += 1
            continue

        # Signal 1 + 4: Tailor clicked (with time delta weighting)
        if key in suggestions_ts:
            try:
                score_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                sugg_ts = datetime.fromisoformat(suggestions_ts[key].replace("Z", "+00:00"))
                delta_sec = (sugg_ts - score_ts).total_seconds()
                delta_sec = max(0, delta_sec)  # ensure non-negative
            except (ValueError, AttributeError):
                delta_sec = 0

            # Fast click → "good", slow click → "ok"
            label = "good" if delta_sec < FAST_CLICK_SEC else "ok"
            labels_to_write[key] = {
                "resume_id": rid,
                "jd_hash": jdh,
                "label": label,
                "source": "implicit",
                "signal": "tailor_clicked",
                "delta_sec": int(delta_sec),
            }
            signal_counts["tailor_clicked"] += 1
            continue

        # Signal 2a: Quick abandon — low score, no tailor, short wait
        # Closes selection-bias gap: users who see a bad score and leave
        # without tailoring are invisible until 2h passes. At score < 40
        # the signal is clear enough to label after only 20 min.
        if key not in suggestions_ts:
            try:
                final_score = float(row.get("final_score") or 0)
                score_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_min = (now - score_ts).total_seconds() / 60
                if final_score < LOW_SCORE_THRESHOLD and age_min > QUICK_ABANDON_MIN:
                    labels_to_write[key] = {
                        "resume_id": rid,
                        "jd_hash": jdh,
                        "label": "bad",
                        "source": "implicit",
                        "signal": "quick_abandon",
                        "final_score": final_score,
                    }
                    signal_counts["quick_abandon"] += 1
                    continue
            except (ValueError, AttributeError):
                pass

        # Signal 2: No-tailor, old enough
        try:
            score_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age = now - score_ts
            if age > timedelta(hours=BAD_LABEL_DELAY_HOURS):
                labels_to_write[key] = {
                    "resume_id": rid,
                    "jd_hash": jdh,
                    "label": "bad",
                    "source": "implicit",
                    "signal": "no_tailor_2h",
                }
                signal_counts["no_tailor_2h"] += 1
        except (ValueError, AttributeError):
            pass

    # Second pass: pairwise session logic (Signal 3)
    # For each session with 2+ JDs: if any JD was tailored, upgrade all tailored to "good",
    # mark non-tailored as "bad"
    for session_key, jd_list in sessions.items():
        if len(set(jdh for jdh, _ in jd_list)) < 2:
            continue  # Single JD in session, no comparison

        rid = session_key[0]  # Extract resume_id from session_key
        tailored_jds = {jdh for jdh, _ in jd_list if (rid, jdh) in suggestions_ts}

        if not tailored_jds:
            continue  # No tailored JDs in this session

        for jdh, _ in jd_list:
            key = (rid, jdh)
            if key in existing_labels or not labels_to_write.get(key):
                continue

            if jdh in tailored_jds:
                # Tailored in session → upgrade to "good" if currently "ok"
                if labels_to_write[key].get("label") == "ok":
                    labels_to_write[key]["label"] = "good"
                    labels_to_write[key]["signal"] = "session_pairwise_upgrade"
            else:
                # Non-tailored but others in session were tailored → strong "bad"
                if labels_to_write[key].get("signal") == "no_tailor_2h":
                    labels_to_write[key]["signal"] = "session_pairwise_bad"
                    signal_counts["session_pairwise"] += 1

    # Write labels
    skipped_existing = 0
    skipped_too_recent = 0
    _DATA.mkdir(parents=True, exist_ok=True)
    with _LABELS.open("a", encoding="utf-8") as f:
        for key, label_dict in labels_to_write.items():
            if key in existing_labels:
                skipped_existing += 1
                continue
            f.write(json.dumps(label_dict) + "\n")

    return {
        "new_labels": len(labels_to_write),
        "skipped_existing": skipped_existing,
        "skipped_too_recent": skipped_too_recent,
        "by_signal": signal_counts,
    }
