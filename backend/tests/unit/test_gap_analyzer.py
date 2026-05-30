"""Unit tests for compute_gap_analysis (pure, no LLM).

Keyword-util internals are monkeypatched so rank/coverage are deterministic;
we assert the analyzer's own logic: rank preservation, per-section filtering,
low-section tiering, and None-score skipping.
"""
from app.api.match_logic import gap_analyzer as ga
from app.models.resume_schema import Resume

RANKED = ["zebra", "alpha", "mango", "kafka", "docker"]


def _patch(monkeypatch, *, section_text):
    monkeypatch.setattr(ga, "_ranked_jd_tokens", lambda jd, k=30: list(RANKED))
    monkeypatch.setattr(ga, "_significant_tokens", lambda text: set())
    monkeypatch.setattr(ga, "_fuzzy_coverage", lambda top, toks, **kw: set())
    monkeypatch.setattr(ga, "_section_text", section_text)


def test_missing_keywords_preserve_frequency_rank(monkeypatch):
    _patch(monkeypatch, section_text=lambda r, s: "content")
    out = ga.compute_gap_analysis(Resume(), "resume", "jd", {})
    # Rank order preserved (NOT alphabetical, which would lead with 'alpha').
    assert out["missing_keywords"] == RANKED
    assert out["missing_keywords"][0] == "zebra"


def test_section_gaps_only_for_nonempty_sections(monkeypatch):
    def _txt(resume, section):
        return "" if section in ("Projects", "Skills") else "has content"
    _patch(monkeypatch, section_text=_txt)
    out = ga.compute_gap_analysis(Resume(), "resume", "jd", {})
    assert set(out["section_gaps"].keys()) == {"Experience", "Summary"}


def test_low_sections_tiers_sorted_and_hinted(monkeypatch):
    _patch(monkeypatch, section_text=lambda r, s: "content")
    scores = {"Experience": 35, "Projects": 50, "Skills": 60, "Summary": 90}
    out = ga.compute_gap_analysis(Resume(), "resume", "jd", scores)
    low = out["low_sections"]
    # 90 excluded (>=65); worst-first ordering.
    assert [s["section"] for s in low] == ["Experience", "Projects", "Skills"]
    assert low[0]["reason"].startswith("Low keyword density")     # <40
    assert low[1]["reason"].startswith("Partial match")           # <55
    assert low[2]["reason"].startswith("Close")                   # 55-64
    # Up to 3 ranked term hints embedded.
    assert "'zebra'" in low[0]["reason"]
    assert all(s["explanation"] == "" for s in low)               # filled later by match.py


def test_none_score_section_skipped(monkeypatch):
    _patch(monkeypatch, section_text=lambda r, s: "content")
    # Summary has no score -> must not appear in low_sections.
    scores = {"Experience": 30, "Summary": None}
    out = ga.compute_gap_analysis(Resume(), "resume", "jd", scores)
    assert [s["section"] for s in out["low_sections"]] == ["Experience"]
