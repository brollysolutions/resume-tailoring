"""Unit tests for diagnose_score (legacy diagnostic still wired into /api/match/)."""
from app.api.match_logic.hybrid_scorer import diagnose_score

_NO_CEIL = {"reasons": [], "exp_required": None, "exp_actual": None}


def test_excellent_tier():
    assert diagnose_score(92, {}, {}, dict(_NO_CEIL))["code"] == "excellent"


def test_good_tier():
    assert diagnose_score(78, {}, {}, dict(_NO_CEIL))["code"] == "good"


def test_experience_gap():
    out = diagnose_score(50, {}, {}, {"reasons": [], "exp_required": 5, "exp_actual": 2})
    assert out["code"] == "experience_gap"
    assert "5+ years" in out["headline"]


def test_seniority_title_gap_parsed():
    ceiling = {"reasons": ["targets senior level (resume reads mid)"], "exp_required": None, "exp_actual": None}
    out = diagnose_score(50, {}, {}, ceiling)
    assert out["code"] == "seniority_title_gap"
    assert "Senior" in out["headline"]


def test_degree_gap():
    ceiling = {"reasons": ["requires bachelor degree"], "exp_required": None, "exp_actual": None}
    out = diagnose_score(50, {}, {}, ceiling)
    assert out["code"] == "degree_gap"


def test_lowest_soft_deficit_wins():
    bd = {"bm25": 30, "skill_coverage": 80, "semantic": 75}
    out = diagnose_score(50, bd, {}, dict(_NO_CEIL))
    assert out["code"] == "low_keywords"


def test_general_fallback_when_no_deficit_below_60():
    bd = {"bm25": 70, "skill_coverage": 70, "semantic": 70}
    out = diagnose_score(50, bd, {}, dict(_NO_CEIL))
    assert out["code"] == "low_general"
