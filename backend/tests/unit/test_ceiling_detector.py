import pytest

from app.api.match_logic.ceiling_detector import (
    parse_jd_hard_requirements,
    estimate_years_experience,
    detect_ceiling,
    infer_seniority,
    resume_has_degree,
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


# --- detect_ceiling -----------------------------------------------------------

_NO_REQS = {"min_years_experience": None, "required_degrees": [], "seniority_level": None}


def test_ceiling_clean_profile_is_100():
    out = detect_ceiling(_resume(("2018", "2024")), dict(_NO_REQS))
    assert out["score"] == 100
    assert out["reasons"] == []


def test_ceiling_experience_gap_penalty_and_reason():
    out = detect_ceiling(_resume(("2022", "2024")), {**_NO_REQS, "min_years_experience": 5})
    # gap=3 -> int(3*8)=24, +15 (gap>=2.5) -> 39 penalty -> 61.
    assert out["score"] == 61
    assert out["exp_required"] == 5
    assert out["exp_actual"] == 2.0
    assert out["reasons"] == ["needs 5+ yrs (resume ~2)"]


def test_ceiling_missing_degree_minus_15():
    out = detect_ceiling(Resume(), {**_NO_REQS, "required_degrees": ["bachelor"]})
    assert out["score"] == 85
    assert out["reasons"] == ["requires bachelor degree"]


def test_ceiling_seniority_gap_reason():
    r = Resume(experience=[ExperienceEntry(title="Junior Developer", company="X")])
    out = detect_ceiling(r, {**_NO_REQS, "seniority_level": "senior"})
    # junior(0) vs senior(2) -> gap 2 -> penalty 24 -> 76.
    assert out["score"] == 76
    assert out["reasons"] == ["targets senior level (resume reads junior)"]


def test_ceiling_floored_at_35():
    r = Resume(experience=[ExperienceEntry(title="Intern", company="X", start_date="2023", end_date="2024")])
    out = detect_ceiling(r, {"min_years_experience": 15, "required_degrees": ["phd"], "seniority_level": "lead"})
    assert out["score"] == 35


# --- infer_seniority ----------------------------------------------------------

def test_infer_seniority_from_recent_title():
    r = Resume(experience=[ExperienceEntry(title="Staff Engineer", company="X")])
    assert infer_seniority(r) == "staff"


def test_infer_seniority_none_when_no_experience():
    assert infer_seniority(Resume()) is None


def test_infer_seniority_none_when_plain_title():
    r = Resume(experience=[ExperienceEntry(title="Software Engineer", company="X")])
    assert infer_seniority(r) is None


# --- resume_has_degree --------------------------------------------------------

def test_has_degree_alias_match():
    r = Resume(education=[{"institution": "U", "degree": "B.S. Computer Science"}])
    assert resume_has_degree(r, ["bachelor"]) is True
    assert resume_has_degree(r, ["master"]) is False


def test_has_degree_empty_required_is_true():
    assert resume_has_degree(Resume(), []) is True
