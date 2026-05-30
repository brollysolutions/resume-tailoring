import json
import pytest
from unittest.mock import AsyncMock

from app.core.ats_simulator import (
    _detect_missing_fields,
    _check_section_recognition,
    _detect_format_warnings,
    _compute_keyword_coverage,
    _compute_parse_score,
    _llm_filter_actionable_keywords,
    run_ats_check,
)
from app.models.resume_schema import Resume


def _make_resume(**kwargs) -> Resume:
    defaults = {
        "name": "Jane Doe",
        "contact": {"email": "jane@example.com", "phone": "555-0100"},
        "experience": [{"title": "Engineer", "company": "Acme", "bullets": ["Built APIs"]}],
        "skills": [{"category": "Languages", "skills": ["Python", "SQL"]}],
    }
    defaults.update(kwargs)
    return Resume(**defaults)


# ---------------------------------------------------------------------------
# _detect_missing_fields
# ---------------------------------------------------------------------------

def test_detect_missing_phone():
    r = _make_resume(contact={"email": "jane@example.com", "phone": ""})
    missing = _detect_missing_fields(r)
    assert "phone" in missing
    assert "email" not in missing


def test_detect_missing_name():
    r = _make_resume(name="")
    assert "name" in _detect_missing_fields(r)


def test_detect_no_missing_fields_when_full():
    r = _make_resume(contact={
        "email": "jane@example.com", "phone": "555-0100",
        "linkedin": "https://linkedin.com/in/jane", "github": "https://github.com/jane",
    })
    missing = _detect_missing_fields(r)
    assert "email" not in missing
    assert "phone" not in missing
    assert "linkedin" not in missing
    assert "github" not in missing


# ---------------------------------------------------------------------------
# _check_section_recognition
# ---------------------------------------------------------------------------

def test_section_recognition_populated():
    r = _make_resume(
        education=[{"institution": "MIT", "degree": "BS CS"}],
        projects=[{"name": "Foo", "bullets": ["did stuff"]}],
    )
    rec = _check_section_recognition(r)
    assert rec["experience"] is True
    assert rec["skills"] is True
    assert rec["education"] is True
    assert rec["projects"] is True


def test_section_recognition_critical_always_present():
    r = Resume(
        name="X",
        contact={},
        experience=[],
        skills=[],
    )
    rec = _check_section_recognition(r)
    assert "experience" in rec
    assert "skills" in rec


# ---------------------------------------------------------------------------
# _detect_format_warnings
# ---------------------------------------------------------------------------

def test_format_warning_extra_section_entries():
    r = _make_resume(extra_sections=[{
        "title": "Awards",
        "content_type": "entries",
        "items": [],
    }])
    warnings = _detect_format_warnings(r)
    assert any("Awards" in w for w in warnings)


def test_format_warning_hidden_skills():
    r = _make_resume(hidden_sections=["skills"])
    warnings = _detect_format_warnings(r)
    assert any("skills" in w.lower() for w in warnings)


def test_no_format_warnings_clean_resume():
    r = _make_resume()
    warnings = _detect_format_warnings(r)
    assert warnings == []


# ---------------------------------------------------------------------------
# _compute_keyword_coverage
# ---------------------------------------------------------------------------

def test_keyword_coverage_partial():
    jd = "Python engineer with experience in AWS Kubernetes Docker CI/CD pipelines"
    r = _make_resume(
        skills=[{"category": "Tech", "skills": ["Python", "AWS"]}],
        experience=[{"title": "SWE", "company": "X", "bullets": ["Used Python and AWS"]}],
    )
    found, missing, score = _compute_keyword_coverage(r, jd)
    assert "python" in found or "Python" in found or any("python" in f.lower() for f in found)
    assert 0 <= score <= 100


def test_keyword_coverage_empty_jd():
    r = _make_resume()
    found, missing, score = _compute_keyword_coverage(r, "")
    assert found == []
    assert missing == []
    assert score == 0


# ---------------------------------------------------------------------------
# _compute_parse_score
# ---------------------------------------------------------------------------

def test_parse_score_full_contact():
    score = _compute_parse_score([], [])
    assert score >= 80


def test_parse_score_missing_email_and_phone():
    score = _compute_parse_score(["email", "phone"], [])
    assert score <= 65


def test_parse_score_format_warnings_reduce_score():
    score_clean = _compute_parse_score([], [])
    score_warn = _compute_parse_score([], ["warning one", "warning two"])
    assert score_warn < score_clean


# ---------------------------------------------------------------------------
# _llm_filter_actionable_keywords
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_llm_filter_strips_noise(mocker):
    mock = mocker.patch("app.core.ats_simulator._chat", new_callable=AsyncMock)
    mock.return_value = json.dumps({"actionable": ["python", "kubernetes"]})
    result = await _llm_filter_actionable_keywords(
        ["python", "kubernetes", "age", "disability", "deadline"], "some jd"
    )
    assert result == ["python", "kubernetes"]


@pytest.mark.asyncio
async def test_llm_filter_prevents_hallucination(mocker):
    mock = mocker.patch("app.core.ats_simulator._chat", new_callable=AsyncMock)
    # LLM hallucinated "java" which wasn't in input
    mock.return_value = json.dumps({"actionable": ["python", "java"]})
    result = await _llm_filter_actionable_keywords(["python", "rust"], "some jd")
    assert "java" not in result
    assert "python" in result


@pytest.mark.asyncio
async def test_llm_filter_fallback_on_error(mocker):
    mock = mocker.patch("app.core.ats_simulator._chat", new_callable=AsyncMock)
    mock.side_effect = Exception("network error")
    candidates = ["python", "aws"]
    result = await _llm_filter_actionable_keywords(candidates, "some jd")
    assert result == candidates


@pytest.mark.asyncio
async def test_llm_filter_empty_input(mocker):
    mock = mocker.patch("app.core.ats_simulator._chat", new_callable=AsyncMock)
    result = await _llm_filter_actionable_keywords([], "some jd")
    assert result == []
    mock.assert_not_called()


# ---------------------------------------------------------------------------
# run_ats_check (integration — LLM mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_ats_check_returns_all_keys(mocker):
    mocker.patch(
        "app.core.ats_simulator._chat", new_callable=AsyncMock,
        return_value=json.dumps({"actionable": ["python", "aws"]}),
    )
    r = _make_resume()
    result = await run_ats_check(r, "Python AWS Kubernetes engineer")
    for key in ("parse_score", "keyword_score", "section_recognition",
                "format_warnings", "missing_fields", "found_keywords",
                "missing_keywords", "suggestions"):
        assert key in result, f"Missing key: {key}"


@pytest.mark.asyncio
async def test_run_ats_check_scores_in_range(mocker):
    mocker.patch(
        "app.core.ats_simulator._chat", new_callable=AsyncMock,
        return_value=json.dumps({"actionable": ["python"]}),
    )
    r = _make_resume()
    result = await run_ats_check(r, "Python AWS Kubernetes engineer")
    assert 0 <= result["parse_score"] <= 100
    assert 0 <= result["keyword_score"] <= 100


@pytest.mark.asyncio
async def test_run_ats_check_keyword_score_recalculated(mocker):
    """keyword_score uses only actionable tokens, not raw token count."""
    mocker.patch(
        "app.core.ats_simulator._chat", new_callable=AsyncMock,
        return_value=json.dumps({"actionable": ["python"]}),
    )
    r = _make_resume(
        skills=[{"category": "Tech", "skills": ["Python"]}],
        experience=[{"title": "SWE", "company": "X", "bullets": ["Used Python daily"]}],
    )
    result = await run_ats_check(r, "Python AWS Kubernetes")
    # python is found, aws+kubernetes are missing but filtered out → 100%
    assert result["keyword_score"] == 100
