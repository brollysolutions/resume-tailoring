"""Background watcher that periodically re-fits scoring weights from labels.

Loop (every N seconds while the app runs):
  1. Run implicit_labeler.derive_labels() to turn fresh suggestion-acceptance
     events into labels.jsonl rows.
  2. If labels.jsonl gained >= TRIGGER_NEW_LABELS rows since the last
     calibration, run tune_weights.run() + calibrate_cosine.run().
  3. Apply the safety gate (Spearman threshold + no-regression check + min N).
     Pass -> weights_store.save_weights() (atomic swap, scorer picks up via mtime).
     Fail -> stage to LAST_ATTEMPT_PATH for admin visibility, keep old weights.

Never raises into the event loop — every iteration is wrapped in try/except so
a single failed run doesn't kill the watcher.

The loop sleep is generous (default 5 min) — calibration is offline-cheap, not
time-critical.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BACKEND = Path(__file__).resolve().parents[2]
_DATA = _BACKEND / "data"
_LABELS = _DATA / "labels.jsonl"
_UPLOAD_EVENTS = _DATA / "upload_events.jsonl"
_STATE_PATH = _DATA / "auto_calibrator_state.json"
_LAST_ATTEMPT_PATH = _DATA / "auto_calibrator_last_attempt.json"

# Tuning knobs — change here, not at call sites.
TRIGGER_NEW_UPLOADS = 5         # re-calibrate after this many new resume uploads
MIN_TOTAL_LABELS = 50           # never trust a fit below this N
REGRESSION_TOLERANCE = 0.02     # new Spearman must be >= old - this
DEFAULT_LOOP_INTERVAL_SEC = 300


def _dynamic_spearman_floor(n_rows: int) -> float:
    """Scale Spearman floor with label count.

    Few labels → noisy signal → accept low correlation.
    Many labels → reliable signal → require stronger correlation.

    N <  100 → 0.20  (early dev / LLM-seeded labels)
    N <  300 → 0.30  (mixed LLM + early real users)
    N >= 300 → 0.40  (production-scale, demand quality)
    """
    if n_rows < 150:
        return 0.20
    if n_rows < 500:
        return 0.30
    return 0.40


def _count_labels() -> int:
    if not _LABELS.exists():
        return 0
    try:
        with _LABELS.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _count_uploads() -> int:
    if not _UPLOAD_EVENTS.exists():
        return 0
    try:
        with _UPLOAD_EVENTS.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def _read_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("auto_calibrator: state write failed: %s", e)


def _write_last_attempt(attempt: dict) -> None:
    try:
        _DATA.mkdir(parents=True, exist_ok=True)
        attempt["recorded_at"] = datetime.now(timezone.utc).isoformat()
        _LAST_ATTEMPT_PATH.write_text(json.dumps(attempt, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("auto_calibrator: last-attempt write failed: %s", e)


def run_calibration_cycle() -> dict:
    """One full cycle: derive labels -> tune -> cosine -> safety gate -> swap.
    Returns a dict describing what happened (also persisted to last-attempt file).
    Safe to call manually from an admin endpoint or test."""
    from app.core.implicit_labeler import derive_labels
    from app.core.weights_store import get_weights, save_weights
    # Import lazily so test environments / fresh deploys don't need scripts on path.
    from scripts.calibration.tune_weights import run as run_tune
    from scripts.calibration.calibrate_cosine import run as run_cosine

    label_summary = derive_labels()
    label_count = _count_labels()
    upload_count = _count_uploads()
    state = _read_state()
    last_calibrated_uploads = int(state.get("last_calibrated_upload_count") or 0)
    new_since_last = upload_count - last_calibrated_uploads

    base = {
        "label_count": label_count,
        "upload_count": upload_count,
        "new_since_last": new_since_last,
        "implicit_labels_added": label_summary,
        "trigger_threshold": TRIGGER_NEW_UPLOADS,
    }

    if new_since_last < TRIGGER_NEW_UPLOADS:
        attempt = {**base, "status": "below_threshold", "swapped": False}
        _write_last_attempt(attempt)
        return attempt

    tune = run_tune()
    if tune["status"] == "insufficient_data":
        attempt = {**base, "status": "tune_insufficient_data", "swapped": False, "tune": tune}
        _write_last_attempt(attempt)
        return attempt

    cos = run_cosine()
    if cos["status"] != "ok":
        attempt = {**base, "status": f"cosine_{cos['status']}", "swapped": False, "tune": tune, "cosine": cos}
        _write_last_attempt(attempt)
        return attempt

    # Safety gate.
    best = tune["best"]
    new_spearman = float(best.get("spearman") or 0.0)
    n_rows = int(tune.get("n_rows") or 0)
    current = get_weights()
    old_spearman = float(current.spearman) if current.spearman is not None else None

    spearman_floor = _dynamic_spearman_floor(n_rows)

    gate_reasons: list[str] = []
    if n_rows < MIN_TOTAL_LABELS:
        gate_reasons.append(f"n_rows {n_rows} < min {MIN_TOTAL_LABELS}")
    if new_spearman < spearman_floor:
        gate_reasons.append(f"spearman {new_spearman} < floor {spearman_floor} (dynamic, N={n_rows})")
    if old_spearman is not None and new_spearman < old_spearman - REGRESSION_TOLERANCE:
        gate_reasons.append(
            f"regression: new {new_spearman} < old {old_spearman} - {REGRESSION_TOLERANCE}"
        )

    if gate_reasons:
        attempt = {
            **base,
            "status": "gate_failed",
            "swapped": False,
            "reasons": gate_reasons,
            "candidate": {**best, "p_low": cos["p_low"], "p_high": cos["p_high"]},
            "spearman_floor": spearman_floor,
            "old_spearman": old_spearman,
        }
        _write_last_attempt(attempt)
        # Record gate failures so we can detect 3-in-a-row.
        fails = int(state.get("consecutive_gate_failures") or 0) + 1
        state["consecutive_gate_failures"] = fails
        _write_state(state)
        return attempt

    save_weights(
        w_kw=best["w_kw"],
        w_skill=best["w_skill"],
        w_ngram=best["w_ngram"],
        w_edu=best["w_edu"],
        w_sen=best["w_sen"],
        w_cos=best["w_cos"],
        p_low=cos["p_low"],
        p_high=cos["p_high"],
        n_rows=n_rows,
        spearman=new_spearman,
        kendall_tau=best.get("kendall_tau"),
        source="auto_calibrator",
    )

    state["last_calibrated_upload_count"] = upload_count
    state["last_calibrated_at"] = datetime.now(timezone.utc).isoformat()
    state["consecutive_gate_failures"] = 0
    _write_state(state)

    attempt = {
        **base,
        "status": "swapped",
        "swapped": True,
        "new_weights": {
            "w_kw": best["w_kw"],
            "w_skill": best["w_skill"],
            "w_ngram": best["w_ngram"],
            "w_edu": best["w_edu"],
            "w_sen": best["w_sen"],
            "w_cos": best["w_cos"],
            "p_low": cos["p_low"],
            "p_high": cos["p_high"],
        },
        "n_rows": n_rows,
        "spearman": new_spearman,
        "kendall_tau": best.get("kendall_tau"),
        "old_spearman": old_spearman,
    }
    _write_last_attempt(attempt)
    return attempt


async def watcher_loop(interval_sec: int = DEFAULT_LOOP_INTERVAL_SEC) -> None:
    """Forever loop. Sleeps `interval_sec` between cycles. Crash-resistant."""
    logger.info("auto_calibrator: watcher started (interval=%ds, trigger=%d new labels)",
                interval_sec, TRIGGER_NEW_LABELS)
    # Small initial delay so startup work finishes first.
    await asyncio.sleep(15)
    while True:
        try:
            result = await asyncio.to_thread(run_calibration_cycle)
            if result.get("swapped"):
                logger.info("auto_calibrator: cycle swapped weights — spearman=%s n=%s",
                            result.get("spearman"), result.get("n_rows"))
            elif result.get("status") != "below_threshold":
                logger.info("auto_calibrator: cycle ran without swap — status=%s",
                            result.get("status"))
        except Exception as e:
            logger.warning("auto_calibrator: cycle crashed (will retry): %s", e)
        await asyncio.sleep(interval_sec)
