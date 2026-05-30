"""Unit tests for per-section scoring helpers.

_section_text rendering and _resolve_section_weights are pure; compute_section_scores
is async and is exercised with embeddings mocked and resume_id=None (so the
section_score_log.jsonl writer short-circuits and nothing touches disk).
"""
from app.api.match_logic.section_scorer import (
    DEFAULT_SECTION_WEIGHTS,
    _resolve_section_weights,
    _section_text,
    compute_section_scores,
)
from app.models.resume_schema import Resume

_FULL = Resume(
    summary="Backend engineer focused on Python and distributed systems.",
    experience=[{"title": "Senior Dev", "company": "Acme", "bullets": ["Built APIs", "Led migration"]}],
    projects=[{"name": "Pipeline", "tech": "Kafka", "bullets": ["Streamed events"]}],
    skills=[{"category": "Languages", "skills": ["Python", "Go"]}],
)


# --- _section_text rendering --------------------------------------------------

def test_section_text_skills_with_category():
    assert _section_text(_FULL, "skills") == "Languages: Python, Go"


def test_section_text_skills_generic_category_drops_label():
    r = Resume(skills=[{"category": "Skills", "skills": ["Python", "Go"]}])
    assert _section_text(r, "skills") == "Python, Go"


def test_section_text_experience_header_and_bullets():
    txt = _section_text(_FULL, "experience")
    assert txt.startswith("Senior Dev @ Acme")
    assert "Built APIs" in txt and "Led migration" in txt


def test_section_text_projects_tech_dash():
    assert _section_text(_FULL, "projects").startswith("Pipeline — Kafka")


def test_section_text_empty_section_is_blank():
    assert _section_text(Resume(), "experience") == ""


# --- _resolve_section_weights -------------------------------------------------

def test_resolve_weights_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr("app.core.weights_store.get_section_weights", lambda name: None)
    assert _resolve_section_weights("experience") == DEFAULT_SECTION_WEIGHTS["experience"]


def test_resolve_weights_uses_calibrated_when_complete(monkeypatch):
    cal = {"w_kw": 0.5, "w_skill": 0.1, "w_ngram": 0.1, "w_edu": 0.0, "w_sen": 0.0, "w_cos": 0.3}
    monkeypatch.setattr("app.core.weights_store.get_section_weights", lambda name: cal)
    assert _resolve_section_weights("skills") == cal


def test_resolve_weights_ignores_incomplete_calibrated(monkeypatch):
    monkeypatch.setattr("app.core.weights_store.get_section_weights", lambda name: {"w_kw": 0.5})
    assert _resolve_section_weights("summary") == DEFAULT_SECTION_WEIGHTS["summary"]


# --- compute_section_scores (async; embeddings mocked, no disk writes) --------

async def test_compute_section_scores_shapes(mock_embedding):
    out = await compute_section_scores(
        _FULL, _FULL.model_dump(), "python kafka backend role",
        jd_embedding=[0.1] * 768, resume_id=None,
    )
    for sec in ("Summary", "Experience", "Projects", "Skills"):
        assert out[sec] is not None
        assert set(out[sec].keys()) == {"score", "features", "weights_used"}
        assert 0 <= out[sec]["score"] <= 100


async def test_compute_section_scores_empty_sections_are_none(mock_embedding):
    r = Resume(summary="Just a summary line about Python engineering.")
    out = await compute_section_scores(
        r, r.model_dump(), "python role", jd_embedding=[0.1] * 768, resume_id=None,
    )
    assert out["Summary"] is not None
    assert out["Experience"] is None
    assert out["Projects"] is None
    assert out["Skills"] is None
