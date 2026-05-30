"""Tests for the unapplied-suggestion collector in apply_suggestions.

Guards against the silent edit-drop: a replace whose `original` matches no
resume line used to vanish with only a log warning. The optional `unapplied`
collector lets callers surface it instead.
"""
from app.core.suggestion_applier import apply_suggestions
from app.models.resume_schema import Resume


def _resume_with_bullet(text: str) -> Resume:
    return Resume(
        name="Test",
        experience=[{"title": "Engineer", "company": "Acme", "bullets": [text]}],
    )


def test_replace_match_applies_and_reports_nothing():
    r = _resume_with_bullet("Built REST APIs serving 2M requests per day.")
    unapplied: list = []
    out = apply_suggestions(
        r,
        [{"section": "Experience", "mode": "replace",
          "original": "Built REST APIs serving 2M requests per day.",
          "suggested": "Built REST and gRPC APIs serving 2M requests per day on AWS."}],
        unapplied=unapplied,
    )
    assert unapplied == []
    assert "gRPC" in out.experience[0].bullets[0]


def test_replace_no_match_is_recorded_not_silently_dropped():
    r = _resume_with_bullet("Built REST APIs serving 2M requests per day.")
    unapplied: list = []
    out = apply_suggestions(
        r,
        [{"section": "Experience", "mode": "replace",
          "original": "Composed a sonnet about distant ocean tides and quiet mountains.",
          "suggested": "irrelevant"}],
        unapplied=unapplied,
    )
    # Resume unchanged, and the miss is surfaced.
    assert out.experience[0].bullets[0] == "Built REST APIs serving 2M requests per day."
    assert len(unapplied) == 1
    assert unapplied[0]["mode"] == "replace"
    assert unapplied[0]["section"] == "Experience"
    assert "matched" in unapplied[0]["reason"]


def test_collector_is_optional_backward_compatible():
    r = _resume_with_bullet("Built REST APIs.")
    # No collector passed — must not raise (existing callers unchanged).
    out = apply_suggestions(
        r,
        [{"section": "Experience", "mode": "replace",
          "original": "nonmatching text here entirely",
          "suggested": "x"}],
    )
    assert isinstance(out, Resume)
