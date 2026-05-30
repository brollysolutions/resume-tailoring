"""Unit tests for the 6-signal hybrid scorer (the core of Match %).

Covers the pure per-signal extractors, the blend math in compute_signals
(including the R4 n-gram redistribution), and the public score_resume_against_jd
wrapper's weights_override path. No network: keyword_coverage / extract_skills
are static, and the cosine path is fed raw vectors directly.
"""
import pytest

from app.api.match_logic import hybrid_scorer as hs
from app.api.match_logic.hybrid_scorer import (
    ScoreInputs,
    _cosine_similarity,
    _edu_signal,
    _kw_signal,
    _ngram_signal,
    _seniority_signal,
    _skill_signal,
    compute_signals,
    score_resume_against_jd,
)
from app.core.weights_store import Weights
from app.models.resume_schema import Resume


def _weights(**over) -> Weights:
    base = {
        "w_kw": 0.30, "w_skill": 0.20, "w_ngram": 0.10,
        "w_edu": 0.05, "w_sen": 0.10, "w_cos": 0.25,
        "p_low": 0.0, "p_high": 1.0,
    }
    base.update(over)
    return Weights.from_dict(base)


# --- _cosine_similarity -------------------------------------------------------

def test_cosine_identical_is_one():
    assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_length_mismatch_is_zero():
    assert _cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


def test_cosine_zero_vector_is_zero():
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_empty_is_zero():
    assert _cosine_similarity([], [1.0]) == 0.0


# --- _kw_signal ---------------------------------------------------------------

def test_kw_signal_blend_70_30(monkeypatch):
    # Required block contains 'REQ', preferred block contains 'PREF'.
    monkeypatch.setattr(
        hs, "keyword_coverage",
        lambda section, resume: 0.8 if "REQ" in section else 0.4,
    )
    jd = "Required:\nPython REQ token\nPreferred:\nGo PREF token\n"
    req, pref, blended = _kw_signal(jd, "resume text")
    assert req == pytest.approx(0.8)
    assert pref == pytest.approx(0.4)
    assert blended == pytest.approx(0.7 * 0.8 + 0.3 * 0.4)


def test_kw_signal_pref_falls_back_to_req_when_no_preferred(monkeypatch):
    monkeypatch.setattr(hs, "keyword_coverage", lambda section, resume: 0.5)
    # No section headers -> entire JD is "required", preferred is "".
    req, pref, blended = _kw_signal("Build scalable services in python", "resume")
    assert pref == req == pytest.approx(0.5)
    assert blended == pytest.approx(0.5)  # 0.7*0.5 + 0.3*0.5


# --- _skill_signal ------------------------------------------------------------

def test_skill_signal_neutral_when_jd_has_no_skills():
    cov, dom, blended = _skill_signal({"skills": []}, "the quick brown fox jumps")
    assert (cov, dom, blended) == (0.0, 1.0, 0.6)


# --- _ngram_signal ------------------------------------------------------------

def test_ngram_inactive_when_jd_has_no_phrases():
    cov, active = _ngram_signal("python developer role", "I write python")
    assert cov == 0.0 and active is False


def test_ngram_active_and_matched():
    # "rest api" is a known _NGRAM_SKILLS phrase.
    cov, active = _ngram_signal("Build a REST API platform", "I built a rest api")
    assert active is True
    assert cov == pytest.approx(1.0)


# --- _edu_signal --------------------------------------------------------------

def test_edu_full_when_no_degree_required():
    assert _edu_signal({}, "We build web apps for fun.") == 1.0


def test_edu_degraded_on_degree_gap():
    resume = Resume(education=[{"institution": "U", "degree": "Bachelor of Science"}])
    # JD requires a PhD; resume tops out at bachelor -> gap of 2 levels.
    edu = _edu_signal(resume.model_dump(), "Requirements: PhD degree required.", resume_obj=resume)
    assert edu == pytest.approx(0.5)  # max(0.3, 1 - 2*0.25)


# --- _seniority_signal --------------------------------------------------------

def test_seniority_full_when_jd_silent():
    assert _seniority_signal({}, "We build apps and ship features.") == 1.0


# --- compute_signals blend + R4 redistribution --------------------------------

def _stub_signals(monkeypatch, *, kw, skill, ngram, active, edu, sen, cosine):
    monkeypatch.setattr(hs, "_kw_signal", lambda jd, rt: (kw, kw, kw))
    monkeypatch.setattr(hs, "_skill_signal", lambda rj, jd: (skill, skill, skill))
    monkeypatch.setattr(hs, "_ngram_signal", lambda jd, rt: (ngram, active))
    monkeypatch.setattr(hs, "_edu_signal", lambda rj, jd, ro=None: edu)
    monkeypatch.setattr(hs, "_seniority_signal", lambda rj, jd, ro=None: sen)
    monkeypatch.setattr(
        hs, "_cosine_signal",
        lambda inputs, p_low, p_high: (cosine, cosine, cosine, None, cosine, None),
    )


def test_compute_signals_blend_when_ngram_active(monkeypatch):
    _stub_signals(monkeypatch, kw=1.0, skill=0.0, ngram=0.0, active=True, edu=0.0, sen=0.0, cosine=0.0)
    sig = compute_signals(ScoreInputs("rt", {}, "jd"), _weights())
    # raw = 1.0*0.30 + 0*0.10 = 0.30
    assert sig.final_score == 30
    assert sig.ngram_active is True


def test_compute_signals_redistributes_wngram_into_wkw_when_inactive(monkeypatch):
    _stub_signals(monkeypatch, kw=1.0, skill=0.0, ngram=0.0, active=False, edu=0.0, sen=0.0, cosine=0.0)
    sig = compute_signals(ScoreInputs("rt", {}, "jd"), _weights())
    # R4: raw = 1.0*(0.30 + 0.10) = 0.40 — NOT boosted by an old 1.0 sentinel.
    assert sig.final_score == 40


def test_compute_signals_clamps_high(monkeypatch):
    _stub_signals(monkeypatch, kw=5.0, skill=5.0, ngram=5.0, active=True, edu=5.0, sen=5.0, cosine=5.0)
    sig = compute_signals(ScoreInputs("rt", {}, "jd"), _weights())
    assert sig.final_score == 100


def test_compute_signals_clamps_low(monkeypatch):
    _stub_signals(monkeypatch, kw=-5.0, skill=-5.0, ngram=0.0, active=True, edu=0.0, sen=0.0, cosine=0.0)
    sig = compute_signals(ScoreInputs("rt", {}, "jd"), _weights())
    assert sig.final_score == 0


# --- score_resume_against_jd weights_override ---------------------------------

def test_score_weights_override_applied(monkeypatch):
    monkeypatch.setattr(hs, "get_weights", lambda: _weights())
    out = score_resume_against_jd(
        "resume text python", {"skills": []}, "python role",
        weights_override={"w_kw": 0.9},
        log_event=False,
    )
    assert out["weights_used"]["w_kw"] == 0.9
    for key in ("bm25", "semantic", "skill_coverage", "ngram", "education", "seniority"):
        assert key in out["breakdown"]
    assert 0 <= out["score"] <= 100
