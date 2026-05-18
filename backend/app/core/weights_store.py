"""Active hybrid-scorer weights backed by a JSON file with mtime-cached reads.

Layout of data/weights_active.json:
    {
      "w_kw": 0.30, "w_skill": 0.20, "w_ngram": 0.10,
      "w_edu": 0.05, "w_sen": 0.10, "w_cos": 0.25,
      "p_low": 0.1789, "p_high": 0.5270,
      "calibrated_at": "2026-05-17T12:00:00+00:00",
      "n_rows": 96, "spearman": 0.4563, "kendall_tau": 0.5818,
      "source": "manual" | "auto_calibrator"
    }

The scorer calls `get_weights()` on every request; we stat the file each call
(cheap) and reload only when mtime changes. Falls back to baked-in defaults if
the file is missing/corrupt so a fresh deploy never crashes.

Writes are atomic via tmp + os.replace. History is preserved under
data/weights_history/weights_{ts}.json on every successful swap.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BACKEND = Path(__file__).resolve().parents[2]
_DATA = _BACKEND / "data"
_ACTIVE = _DATA / "weights_active.json"
_HISTORY_DIR = _DATA / "weights_history"


DEFAULTS = {
    "w_kw": 0.30,
    "w_skill": 0.20,
    "w_ngram": 0.10,
    "w_edu": 0.05,
    "w_sen": 0.10,
    "w_cos": 0.25,
    "p_low": 0.1789,
    "p_high": 0.5270,
    "calibrated_at": None,
    "n_rows": 0,
    "spearman": None,
    "kendall_tau": None,
    "source": "defaults",
}


@dataclass(frozen=True)
class Weights:
    w_kw: float
    w_skill: float
    w_ngram: float
    w_edu: float
    w_sen: float
    w_cos: float
    p_low: float
    p_high: float
    calibrated_at: Optional[str]
    n_rows: int
    spearman: Optional[float]
    kendall_tau: Optional[float]
    source: str

    @classmethod
    def from_dict(cls, d: dict) -> "Weights":
        merged = {**DEFAULTS, **d}
        return cls(
            w_kw=float(merged["w_kw"]),
            w_skill=float(merged["w_skill"]),
            w_ngram=float(merged["w_ngram"]),
            w_edu=float(merged["w_edu"]),
            w_sen=float(merged["w_sen"]),
            w_cos=float(merged["w_cos"]),
            p_low=float(merged["p_low"]),
            p_high=float(merged["p_high"]),
            calibrated_at=merged.get("calibrated_at"),
            n_rows=int(merged.get("n_rows") or 0),
            spearman=merged.get("spearman"),
            kendall_tau=merged.get("kendall_tau"),
            source=str(merged.get("source") or "defaults"),
        )


_lock = threading.Lock()
_cached: Optional[Weights] = None
_cached_mtime: Optional[float] = None


def _load_from_disk() -> Optional[Weights]:
    if not _ACTIVE.exists():
        return None
    try:
        data = json.loads(_ACTIVE.read_text(encoding="utf-8"))
        return Weights.from_dict(data)
    except Exception as e:
        logger.warning("weights_store: failed to load %s, using defaults: %s", _ACTIVE, e)
        return None


def get_weights() -> Weights:
    """Return active weights. Reloads from disk if mtime changed."""
    global _cached, _cached_mtime

    try:
        mtime = _ACTIVE.stat().st_mtime if _ACTIVE.exists() else None
    except OSError:
        mtime = None

    if _cached is not None and mtime == _cached_mtime:
        return _cached

    with _lock:
        try:
            mtime = _ACTIVE.stat().st_mtime if _ACTIVE.exists() else None
        except OSError:
            mtime = None
        if _cached is not None and mtime == _cached_mtime:
            return _cached

        loaded = _load_from_disk()
        if loaded is None:
            loaded = Weights.from_dict(DEFAULTS)
        _cached = loaded
        _cached_mtime = mtime
        return _cached


def save_weights(
    w_kw: float,
    w_skill: float,
    w_ngram: float,
    w_edu: float,
    w_sen: float,
    w_cos: float,
    p_low: float,
    p_high: float,
    n_rows: int,
    spearman: Optional[float] = None,
    kendall_tau: Optional[float] = None,
    source: str = "auto_calibrator",
) -> Weights:
    """Atomic swap of active weights. Also archives a copy to history.
    Caller is responsible for safety-gating (call this only when checks pass)."""
    payload = {
        "w_kw": round(float(w_kw), 4),
        "w_skill": round(float(w_skill), 4),
        "w_ngram": round(float(w_ngram), 4),
        "w_edu": round(float(w_edu), 4),
        "w_sen": round(float(w_sen), 4),
        "w_cos": round(float(w_cos), 4),
        "p_low": round(float(p_low), 4),
        "p_high": round(float(p_high), 4),
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(n_rows),
        "spearman": round(float(spearman), 4) if spearman is not None else None,
        "kendall_tau": round(float(kendall_tau), 4) if kendall_tau is not None else None,
        "source": source,
    }

    _DATA.mkdir(parents=True, exist_ok=True)
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    tmp = _ACTIVE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, _ACTIVE)

    ts = payload["calibrated_at"].replace(":", "-")
    history_path = _HISTORY_DIR / f"weights_{ts}.json"
    try:
        history_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("weights_store: history write failed (non-fatal): %s", e)

    global _cached, _cached_mtime
    with _lock:
        _cached = None
        _cached_mtime = None

    logger.info(
        "weights_store: swapped weights kw=%.2f skill=%.2f ngram=%.2f edu=%.2f sen=%.2f cos=%.2f "
        "remap=[%.4f, %.4f] N=%d spearman=%s source=%s",
        payload["w_kw"], payload["w_skill"], payload["w_ngram"],
        payload["w_edu"], payload["w_sen"], payload["w_cos"],
        payload["p_low"], payload["p_high"],
        payload["n_rows"], payload["spearman"], payload["source"],
    )

    return Weights.from_dict(payload)


def history(limit: int = 20) -> list[dict]:
    """Newest-first list of past weight snapshots."""
    if not _HISTORY_DIR.exists():
        return []
    files = sorted(_HISTORY_DIR.glob("weights_*.json"), reverse=True)
    out: list[dict] = []
    for p in files[:limit]:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def as_dict(w: Weights) -> dict:
    return asdict(w)
