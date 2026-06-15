"""Unit tests for build_improvement_plan (pure, no LLM)."""
from types import SimpleNamespace

import pytest

from app.api.match_logic import improvement_planner as ip
from app.api.match_logic.improvement_planner import build_improvement_plan


@pytest.fixture
def patch_helpers(monkeypatch):
    """Control N (top-JD size) and skill classification deterministically."""

    def _setup(n_tokens: int, skill_words: set[str]):
        monkeypatch.setattr(
            ip, "_top_jd_tokens", lambda jd, k=30: {f"t{i}" for i in range(n_tokens)}
        )
        monkeypatch.setattr(
            ip, "extract_skills", lambda kw: {kw} if kw in skill_words else set()
        )

    return _setup


def _weights(w_kw=0.4):
    return SimpleNamespace(w_kw=w_kw)


def test_est_gain_math(patch_helpers):
    # N=20, w_kw=0.4 -> per_kw = 0.4/20*100 = 2.0; 3 skills -> round(3*2)=6
    patch_helpers(20, {"docker", "kubernetes", "terraform"})
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Experience": 60, "Skills": 50},
        current_score=70,
        ceiling={"score": 100, "reasons": []},
        gap_analysis={"missing_keywords": ["docker", "kubernetes", "terraform"]},
        weights=_weights(),
    )
    assert len(plan["actions"]) == 1
    act = plan["actions"][0]
    assert act["section"] == "Skills"
    assert act["kind"] == "add_keywords"
    assert act["est_gain"] == 6
    assert plan["achievable_ceiling"] == 76  # 70 + 6


def test_no_double_count(patch_helpers):
    # "python" is a skill, "leadership" is not -> disjoint groups, each kw once.
    patch_helpers(20, {"python"})
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Experience": 40, "Projects": 80, "Summary": 90},
        current_score=70,
        ceiling={"score": 100, "reasons": []},
        gap_analysis={"missing_keywords": ["python", "leadership"]},
        weights=_weights(),
    )
    sections = {a["section"] for a in plan["actions"]}
    assert sections == {"Skills", "Experience"}  # weakest narrative section
    all_kws = [k for a in plan["actions"] for k in a["keywords"]]
    assert sorted(all_kws) == ["leadership", "python"]
    assert len(all_kws) == len(set(all_kws))  # no duplicates


def test_est_gain_floor_one(patch_helpers):
    # N=200 -> per_kw=0.2 -> round(1*0.2)=0, must floor to 1.
    patch_helpers(200, {"docker"})
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Skills": 50},
        current_score=70,
        ceiling={"score": 100, "reasons": []},
        gap_analysis={"missing_keywords": ["docker"]},
        weights=_weights(),
    )
    assert plan["actions"][0]["est_gain"] == 1


def test_keywords_capped_per_action(patch_helpers):
    # 8 missing skills -> action surfaces at most _MAX_KEYWORDS_PER_ACTION (5).
    skills = {f"s{i}" for i in range(8)}
    patch_helpers(20, skills)
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Skills": 50},
        current_score=10,
        ceiling={"score": 100, "reasons": []},
        gap_analysis={"missing_keywords": sorted(skills)},
        weights=_weights(),
    )
    assert len(plan["actions"]) == 1
    assert len(plan["actions"][0]["keywords"]) == ip._MAX_KEYWORDS_PER_ACTION


def test_gains_clipped_to_100_headroom(patch_helpers):
    # N=2 -> per_kw=20; capped 5 skills -> raw=round(... )>>5 headroom from 95.
    patch_helpers(2, {"a", "b", "c"})
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Skills": 50},
        current_score=95,
        ceiling={"score": 100, "reasons": []},
        gap_analysis={"missing_keywords": ["a", "b", "c"]},
        weights=_weights(),
    )
    assert plan["actions"][0]["est_gain"] == 5  # clipped to 100 - 95
    assert plan["achievable_ceiling"] == 100


def test_blocker_does_not_cap_number(patch_helpers):
    # Hard-requirement blocker is prose only; achievable = current + shown gains,
    # NOT clamped down to the hard ceiling (live scorer ignores that ceiling).
    patch_helpers(8, {"a", "b", "c", "d", "e"})  # per_kw=5, 5 skills -> raw=25
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Skills": 50},
        current_score=50,
        ceiling={"score": 35, "reasons": ["targets lead level"]},
        gap_analysis={"missing_keywords": ["a", "b", "c", "d", "e"]},
        weights=_weights(),
    )
    assert plan["actions"][0]["est_gain"] == 25
    assert plan["achievable_ceiling"] == 75  # 50 + 25, ignores ceiling score 35
    assert plan["blockers"] == [{"reason": "targets lead level", "kind": "seniority"}]


def test_empty_missing_no_actions(patch_helpers):
    patch_helpers(20, set())
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Skills": 88},
        current_score=88,
        ceiling={"score": 100, "reasons": []},
        gap_analysis={"missing_keywords": []},
        weights=_weights(),
    )
    assert plan["actions"] == []
    assert plan["achievable_ceiling"] == 88


def test_no_actions_when_at_100(patch_helpers):
    patch_helpers(20, {"docker"})
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={"Skills": 90},
        current_score=100,
        ceiling={"score": 100, "reasons": []},
        gap_analysis={"missing_keywords": ["docker"]},
        weights=_weights(),
    )
    assert plan["actions"] == []  # no headroom
    assert plan["achievable_ceiling"] == 100


def test_blockers_passthrough_with_kinds(patch_helpers):
    patch_helpers(20, set())
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={},
        current_score=60,
        ceiling={
            "score": 60,
            "reasons": [
                "needs 5+ yrs (resume ~2)",
                "requires Bachelor degree",
                "targets senior level (resume reads mid)",
            ],
        },
        gap_analysis={"missing_keywords": []},
        weights=_weights(),
    )
    kinds = [b["kind"] for b in plan["blockers"]]
    assert kinds == ["experience", "education", "seniority"]


def test_handles_none_gap_and_ceiling(patch_helpers):
    patch_helpers(20, set())
    plan = build_improvement_plan(
        jd_text="jd",
        section_scores={},
        current_score=72,
        ceiling=None,
        gap_analysis=None,
        weights=_weights(),
    )
    assert plan["actions"] == []
    assert plan["blockers"] == []
    assert plan["achievable_ceiling"] == 72
