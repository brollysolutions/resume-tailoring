"""Regression tests for the duplicate-skills / "Unknown" rendering bug.

`_dedupe_canonical_extra_sections` drops extra_sections whose title is a synonym
of a populated canonical field (the LLM occasionally emits e.g. "TECHNICAL SKILLS"
as BOTH `skills` and an extra_section, which renders twice). The "unknown" null
sentinel collapses literal "Unknown" dates to None.
"""
from app.core.extractor import _dedupe_canonical_extra_sections
from app.models.resume_schema import ProjectEntry, Resume


def test_dedupe_drops_canonical_extra_keeps_others():
    resume = Resume(
        skills=[{"category": "Backend", "skills": ["Python", "Django"]}],
        extra_sections=[
            {"title": "TECHNICAL SKILLS", "content_type": "entries",
             "items": [{"header": "Backend", "bullets": ["Python", "Django"]}]},
            {"title": "Hobbies", "content_type": "list",
             "items": [{"text": "Chess"}]},
        ],
    )

    _dedupe_canonical_extra_sections(resume)

    titles = [ex.title for ex in resume.extra_sections]
    assert "TECHNICAL SKILLS" not in titles
    assert "Hobbies" in titles
    assert resume.skills  # canonical field untouched


def test_dedupe_keeps_canonical_extra_when_field_empty():
    # If the canonical field has NO content, the extra is the only copy — keep it.
    resume = Resume(
        skills=[],
        extra_sections=[
            {"title": "Skills", "content_type": "entries",
             "items": [{"header": "Backend", "bullets": ["Python"]}]},
        ],
    )

    _dedupe_canonical_extra_sections(resume)

    assert [ex.title for ex in resume.extra_sections] == ["Skills"]


def test_unknown_date_collapses_to_none():
    assert ProjectEntry(name="ATS", date="Unknown").date is None
    assert ProjectEntry(name="ATS", date="unknown").date is None
    assert ProjectEntry(name="ATS", date="2024").date == "2024"
