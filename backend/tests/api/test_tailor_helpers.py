"""Unit tests for pure helpers in app.api.tailor (no HTTP, no mocks needed)."""
from app.api.tailor import _fix_project_name, _replace_projects, _scrub_locations
from app.models.resume_schema import Resume


# --- _scrub_locations ---------------------------------------------------------

def test_scrub_strips_x_based_phrasing():
    assert _scrub_locations("Bangalore-based Onboarding System") == "Onboarding System"


def test_scrub_strips_geo_token():
    assert _scrub_locations("Hyderabad Analytics") == "Analytics"


def test_scrub_empty_passthrough():
    assert _scrub_locations("") == ""


# --- _fix_project_name --------------------------------------------------------

def test_fix_drops_trailing_preposition():
    assert _fix_project_name("Event-Driven System for") == "Event-Driven System"


def test_fix_single_word_becomes_empty():
    assert _fix_project_name("Kafka") == ""


def test_fix_keeps_valid_name():
    assert _fix_project_name("Realtime Data Pipeline") == "Realtime Data Pipeline"


def test_fix_empty_passthrough():
    assert _fix_project_name("") == ""


# --- _replace_projects (index merge) ------------------------------------------

def _resume_with_projects(n):
    return Resume(projects=[{"name": f"Old{i}", "tech": "T", "bullets": [f"b{i}"]} for i in range(n)])


def test_replace_by_index_keeps_trailing_existing():
    r = _resume_with_projects(2)
    out = _replace_projects(r, [{"name": "New0", "tech": "X", "bullets": ["nb"]}])
    assert [p.name for p in out.projects] == ["New0", "Old1"]


def test_replace_appends_extra_new():
    r = _resume_with_projects(1)
    out = _replace_projects(r, [{"name": "New0"}, {"name": "New1"}])
    assert [p.name for p in out.projects] == ["New0", "New1"]


def test_replace_empty_new_is_noop():
    r = _resume_with_projects(2)
    out = _replace_projects(r, [])
    assert [p.name for p in out.projects] == ["Old0", "Old1"]
