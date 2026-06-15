"""Guard tests against the "tailoring lowers the score" inversion.

Root cause was a cosine remap whose floor (p_low) sat inside the real operating
band (~0.59-0.73), so normal embedding drift collapsed the cosine signal to ~0
and capped the ceiling well below 100. These tests lock in two properties:

1. The remap is monotonic in raw cosine (higher cosine never lowers the signal).
2. With the re-anchored band [0.45, 0.80], a typical raw cosine is NOT floored
   and a strong cosine maps high enough that the ceiling is reachable.

They use the pure helpers (no embeddings) so they are deterministic regardless
of the live weights_active.json.
"""
import pytest

from app.api.match_logic import hybrid_scorer as hs
from app.api.match_logic.hybrid_scorer import ScoreInputs, compute_signals
from app.core.weights_store import Weights


# Re-anchored remap band chosen by the ceiling fix (2026-05-29). Kept here so a
# future change that pushes p_low back into the operating band trips a test.
P_LOW, P_HIGH = 0.45, 0.80


def _blended(raw: float, p_low: float = P_LOW, p_high: float = P_HIGH) -> float:
    """Section-weighted cosine blended value for a uniform raw cosine."""
    inp = ScoreInputs(
        resume_text="", resume_json={}, jd_text="",
        section_cosines={"Skills": raw, "Experience": raw, "Projects": raw, "Summary": raw},
    )
    return hs._cosine_signal(inp, p_low, p_high)[2]


def _weights(**over) -> Weights:
    base = {
        "w_kw": 0.35, "w_skill": 0.25, "w_ngram": 0.10,
        "w_edu": 0.05, "w_sen": 0.10, "w_cos": 0.15,
        "p_low": P_LOW, "p_high": P_HIGH,
    }
    base.update(over)
    return Weights.from_dict(base)


# --- remap monotonicity -------------------------------------------------------

@pytest.mark.parametrize("lo,hi", [(0.50, 0.60), (0.59, 0.66), (0.66, 0.73), (0.73, 0.80)])
def test_remap_monotonic_increasing(lo, hi):
    assert _blended(hi) >= _blended(lo)


def test_remap_strictly_increases_across_operating_band():
    vals = [_blended(r) for r in (0.55, 0.60, 0.65, 0.70, 0.75)]
    assert vals == sorted(vals)
    # And they are genuinely distinct, not all clamped to one value.
    assert len(set(round(v, 4) for v in vals)) == len(vals)


# --- no cliff / ceiling reachable for the chosen anchors ----------------------

def test_operating_band_floor_not_zeroed():
    # The old p_low=0.59 floored the bottom of the band to 0. The re-anchored
    # band must give a band-floor cosine a meaningful (non-trivial) value.
    assert _blended(0.59) > 0.20


def test_strong_cosine_maps_high():
    # A strong section match must be able to drive the cosine term near full,
    # so a genuinely strong resume can exceed the old ~85 ceiling.
    assert _blended(0.75) >= 0.70


def test_plow_safely_below_operating_band():
    # Guards against re-introducing the cliff: p_low must sit below the empirical
    # operating floor (~0.59) so normal drift cannot push cosine under the floor.
    assert P_LOW < 0.59


# --- final score is monotonic in cosine (the inversion guard) -----------------

def test_final_score_non_decreasing_in_cosine(monkeypatch):
    w = _weights()
    monkeypatch.setattr(hs, "_kw_signal", lambda jd, rt: (0.9, 0.9, 0.9))
    monkeypatch.setattr(hs, "_skill_signal", lambda rj, jd: (1.0, 1.0, 1.0))
    monkeypatch.setattr(hs, "_ngram_signal", lambda jd, rt: (0.0, True))
    monkeypatch.setattr(hs, "_edu_signal", lambda rj, jd, ro=None: 1.0)
    monkeypatch.setattr(hs, "_seniority_signal", lambda rj, jd, ro=None: 1.0)

    scores = []
    for cos in (0.0, 0.25, 0.5, 0.75, 1.0):
        monkeypatch.setattr(
            hs, "_cosine_signal",
            lambda inputs, p_low, p_high, _c=cos: (_c, _c, _c, _c, _c, None),
        )
        scores.append(compute_signals(ScoreInputs("rt", {}, "jd"), w).final_score)

    assert scores == sorted(scores), f"score must not drop as cosine rises: {scores}"


def test_ceiling_reachable_above_85(monkeypatch):
    # Strong everything (kw high, skill/edu/sen full) + a strong real cosine
    # (0.75 -> remapped ~0.857) must clear the old ~85 ceiling.
    w = _weights()
    monkeypatch.setattr(hs, "_kw_signal", lambda jd, rt: (0.95, 0.95, 0.95))
    monkeypatch.setattr(hs, "_skill_signal", lambda rj, jd: (1.0, 1.0, 1.0))
    monkeypatch.setattr(hs, "_ngram_signal", lambda jd, rt: (1.0, True))
    monkeypatch.setattr(hs, "_edu_signal", lambda rj, jd, ro=None: 1.0)
    monkeypatch.setattr(hs, "_seniority_signal", lambda rj, jd, ro=None: 1.0)
    remapped = _blended(0.75)
    monkeypatch.setattr(
        hs, "_cosine_signal",
        lambda inputs, p_low, p_high: (remapped, remapped, remapped, 0.75, remapped, None),
    )
    sig = compute_signals(ScoreInputs("rt", {}, "jd"), w)
    assert sig.final_score > 85
