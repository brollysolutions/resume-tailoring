"""Train/test split utilities for calibration eval (R7).

Provides resume-stratified and time-stratified splits so tune_weights.run()
can report held-out Spearman ρ alongside in-sample fit.
"""
from __future__ import annotations

import random


def train_test_split_by_resume(
    rows: list[dict],
    test_fraction: float = 0.20,
    seed: int = 0,
) -> tuple[list[dict], list[dict]]:
    """Group-aware split: same resume_id never in both sets.

    Returns (rows, []) if fewer than 5 unique resume_ids — not enough
    for a meaningful held-out set at current label volume.
    """
    resume_ids = list({r["resume_id"] for r in rows})
    if len(resume_ids) < 5:
        return rows, []
    rng = random.Random(seed)
    rng.shuffle(resume_ids)
    n_test = max(1, round(len(resume_ids) * test_fraction))
    test_ids = set(resume_ids[:n_test])
    train = [r for r in rows if r["resume_id"] not in test_ids]
    test  = [r for r in rows if r["resume_id"]     in test_ids]
    return train, test


def train_test_split_by_time(
    rows: list[dict],
    test_fraction: float = 0.20,
) -> tuple[list[dict], list[dict]]:
    """Hold out the newest rows by ts field."""
    sorted_rows = sorted(rows, key=lambda r: r.get("ts", ""))
    n_test = max(1, round(len(sorted_rows) * test_fraction))
    return sorted_rows[:-n_test], sorted_rows[-n_test:]
