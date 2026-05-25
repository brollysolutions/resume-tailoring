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
    "w_kw": 0.40,
    "w_skill": 0.20,
    "w_ngram": 0.10,
    "w_edu": 0.05,
    "w_sen": 0.00,
    "w_cos": 0.25,
    "p_low": 0.1789,
    "p_high": 0.5270,
    "calibrated_at": None,
    "n_rows": 0,
    "spearman": None,
    "kendall_tau": None,
    "source": "defaults",
    # Optional calibrated per-section weights — falls back to hand-tuned
    # DEFAULT_SECTION_WEIGHTS in section_scorer.py if absent/empty.
    # Shape: {section_name: {w_kw, w_skill, w_ngram, w_edu, w_sen, w_cos, spearman, n_rows}}
    "section_weights": {},
    # R7: held-out eval split fields. Null on pre-R7 entries (backward-compat).
    "spearman_train": None,
    "spearman_test": None,
    "n_train": 0,
    "n_test": 0,
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
    # Per-section calibrated weights (empty = use defaults from section_scorer)
    section_weights: dict = None  # type: ignore[assignment]
    # R7: held-out eval split ρ. None on pre-R7 entries.
    spearman_train: Optional[float] = None
    spearman_test: Optional[float] = None
    n_train: int = 0
    n_test: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "Weights":
        merged = {**DEFAULTS, **d}
        sw = merged.get("section_weights") or {}
        if not isinstance(sw, dict):
            sw = {}
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
            section_weights=sw,
            spearman_train=merged.get("spearman_train"),
            spearman_test=merged.get("spearman_test"),
            n_train=int(merged.get("n_train") or 0),
            n_test=int(merged.get("n_test") or 0),
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


def get_section_weights(section_name: str) -> Optional[dict]:
    """Return calibrated weights for a section, or None if not present.

    Caller falls back to hand-tuned DEFAULT_SECTION_WEIGHTS in section_scorer.
    Section name is matched case-insensitively (stored as lowercase).
    """
    w = get_weights()
    if not w.section_weights:
        return None
    return w.section_weights.get(section_name.lower())


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
    section_weights: Optional[dict] = None,
    spearman_train: Optional[float] = None,
    spearman_test: Optional[float] = None,
    n_train: int = 0,
    n_test: int = 0,
) -> Weights:
    """Atomic swap of active weights. Also archives a copy to history.
    Caller is responsible for safety-gating (call this only when checks pass).

    If section_weights is None, the existing section_weights field is preserved
    (so a global-only calibration cycle doesn't wipe calibrated section data).
    """
    # Preserve existing section_weights if caller doesn't pass new ones.
    if section_weights is None:
        try:
            existing = get_weights()
            section_weights = dict(existing.section_weights or {})
        except Exception:
            section_weights = {}

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
        "section_weights": section_weights or {},
        "spearman_train": round(float(spearman_train), 4) if spearman_train is not None else None,
        "spearman_test": round(float(spearman_test), 4) if spearman_test is not None else None,
        "n_train": int(n_train),
        "n_test": int(n_test),
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
