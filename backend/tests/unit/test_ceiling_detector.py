import pytest

from app.api.match_logic.ceiling_detector import (
    parse_jd_hard_requirements,
    estimate_years_experience,
)
from app.models.resume_schema import Resume, ExperienceEntry


def _resume(*spans):
    """spans: (start_date, end_date) tuples."""
    return Resume(experience=[ExperienceEntry(start_date=s, end_date=e) for s, e in spans])


# --- JD requirement parsing ---------------------------------------------------

def test_jd_label_range_lower_bound():
    reqs = parse_jd_hard_requirements("🔹 Experience: 1–3 Years")
    assert reqs["min_years_experience"] == 1


def test_jd_label_plus():
    reqs = parse_jd_hard_requirements("Experience – 2+ Years")
    assert reqs["min_years_experience"] == 2


def test_jd_of_experience_form_regression():
    reqs = parse_jd_hard_requirements("3+ years of experience required")
    assert reqs["min_years_experience"] == 3


def test_jd_company_fluff_ignored():
    reqs = parse_jd_hard_requirements("We have over 20 years of experience building products.")
    assert reqs["min_years_experience"] is None


# --- Resume years estimation --------------------------------------------------

def test_month_name_precision():
    assert estimate_years_experience(_resume(("Jan 2022", "Mar 2024"))) == 2.2


def test_bare_years():
    assert estimate_years_experience(_resume(("2022", "2024"))) == 2.0


def test_numeric_mm_yyyy_regression():
    assert estimate_years_experience(_resume(("01/2022", "01/2024"))) == 2.0


def test_collapsed_range_in_start_field():
    assert estimate_years_experience(_resume(("Jan 2022 - Present", None))) > 0


def test_collapsed_bare_year_range():
    assert estimate_years_experience(_resume(("2020 - 2022", None))) == 2.0


def test_month_only_no_year_does_not_zero_other_entries():
    # First entry parses to 2.0; second is month-only-no-year and must be skipped,
    # not zero out the total.
    yrs = estimate_years_experience(_resume(("2020", "2022"), ("Jan", "Mar")))
    assert yrs == 2.0


def test_no_dates_returns_none():
    assert estimate_years_experience(_resume((None, None))) is None
