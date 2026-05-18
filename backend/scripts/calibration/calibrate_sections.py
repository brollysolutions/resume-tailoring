"""Analyze per-section score reliability from section_deltas.jsonl.

For each section (Skills, Experience, Projects, Summary, Education):
- Compute correlation between before_score and score_delta
- High before + large delta → section scorer overconfident
- Produces human-readable report + JSON output

Run: python backend/scripts/calibration/calibrate_sections.py
Output: data/section_calibration.json + console report
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from statistics import correlation, mean, stdev

logger = logging.getLogger(__name__)

_BACKEND = Path(__file__).resolve().parents[3] / "app"
_DATA = _BACKEND.parent / "data"
_SECTION_DELTAS = _DATA / "section_deltas.jsonl"
_OUTPUT = _DATA / "section_calibration.json"

SECTION_ORDER = ["Summary", "Experience", "Projects", "Skills", "Education"]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def run() -> dict:
    """Analyze section delta correlation."""
    deltas = _load_jsonl(_SECTION_DELTAS)
    if not deltas:
        print("No section_deltas.jsonl found.")
        return {}

    # Gather per-section (before_score, delta) pairs
    section_data: dict[str, list[tuple[int, int]]] = {s: [] for s in SECTION_ORDER}
    for row in deltas:
        before_secs = row.get("before_sections") or {}
        after_secs = row.get("after_sections") or {}
        delta = row.get("score_delta", 0)
        for section in SECTION_ORDER:
            before = before_secs.get(section)
            if before is not None:
                section_data[section].append((int(before), int(delta)))

    # Compute stats per section
    results = {}
    for section in SECTION_ORDER:
        pairs = section_data[section]
        if len(pairs) < 5:
            results[section] = {
                "n": len(pairs),
                "correlation": None,
                "reliability": "insufficient_data",
                "mean_before": None,
                "mean_delta": None,
            }
            continue

        befores = [b for b, _ in pairs]
        deltas_list = [d for _, d in pairs]

        try:
            corr = correlation(befores, deltas_list)
        except (ValueError, StopIteration):
            corr = None

        mean_before = mean(befores) if befores else None
        mean_delta = mean(deltas_list) if deltas_list else None

        # Reliability heuristic:
        # - If before=90 but delta=30+ → likely overconfident
        # - If strong negative correlation → good (high before → low delta = well-calibrated)
        reliability = "unknown"
        if corr is not None:
            if corr < -0.3:
                reliability = "well_calibrated"  # high score → low delta
            elif corr > 0.3:
                reliability = "overconfident"  # high score → high delta
            elif -0.3 <= corr <= 0.3:
                reliability = "neutral"

        results[section] = {
            "n": len(pairs),
            "correlation": round(corr, 3) if corr else None,
            "reliability": reliability,
            "mean_before": round(mean_before, 1) if mean_before else None,
            "mean_delta": round(mean_delta, 1) if mean_delta else None,
        }

    return results


def main():
    results = run()
    if not results:
        return

    print("\n" + "=" * 60)
    print("PER-SECTION RELIABILITY REPORT")
    print("=" * 60)
    for section in SECTION_ORDER:
        r = results.get(section, {})
        n = r.get("n", 0)
        corr = r.get("correlation")
        rel = r.get("reliability", "?")
        mean_b = r.get("mean_before")
        mean_d = r.get("mean_delta")

        print(f"\n{section:15} (n={n})")
        if n < 5:
            print(f"  Insufficient data (need ≥5 samples)")
            continue

        print(f"  Correlation (before vs delta): {corr}")
        print(f"  Reliability: {rel}")
        print(f"  Avg before: {mean_b}, Avg delta: {mean_d}")

        if rel == "well_calibrated":
            print(f"  ✓ This section's scorer is well-calibrated.")
        elif rel == "overconfident":
            print(f"  ✗ Likely OVERCONFIDENT: high scores don't improve much with tailoring.")
        elif rel == "neutral":
            print(f"  ~ Neutral: no clear pattern. May need more data.")

    # Write JSON output
    output_dict = {
        "results": results,
        "summary": {
            "sections_calibrated": sum(1 for r in results.values() if r.get("reliability") != "unknown"),
            "sections_overconfident": sum(1 for r in results.values() if r.get("reliability") == "overconfident"),
        },
    }
    _DATA.mkdir(parents=True, exist_ok=True)
    with _OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(output_dict, f, indent=2)
    print(f"\nResults written to {_OUTPUT}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
