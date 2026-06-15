import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Read-only / render endpoints
# ---------------------------------------------------------------------------

def test_templates_list(client):
    r = client.get("/api/tailor/templates")
    assert r.status_code == 200
    assert "templates" in r.json()


def test_sample_preview_html(client):
    r = client.get("/api/tailor/sample-preview?template_id=standard")
    assert r.status_code == 200
    assert "html" in r.json()


def test_preview_happy(client, resume_id):
    r = client.post(
        "/api/tailor/preview",
        json={"resume_id": resume_id, "suggestions": [], "template_id": "standard"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "html"
    assert "html" in body


def test_preview_unknown_resume_404(client):
    r = client.post("/api/tailor/preview", json={"resume_id": "nope", "suggestions": []})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /apply — streamed PDF / DOCX
# ---------------------------------------------------------------------------

def test_apply_pdf(client, resume_id, mocker):
    mocker.patch("app.api.tailor.render_pdf", return_value=b"%PDF-1.4 fake")
    mocker.patch("app.core.rag_service.RAGService.refresh_from_resume", new=AsyncMock())
    r = client.post(
        "/api/tailor/apply",
        json={"resume_id": resume_id, "suggestions": [], "format": "pdf", "template_id": "standard"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]


def test_apply_docx(client, resume_id, mocker):
    mocker.patch("app.api.tailor.render_docx", return_value=b"PK fake docx")
    mocker.patch("app.core.rag_service.RAGService.refresh_from_resume", new=AsyncMock())
    r = client.post(
        "/api/tailor/apply",
        json={"resume_id": resume_id, "suggestions": [], "format": "docx", "template_id": "standard"},
    )
    assert r.status_code == 200
    assert "wordprocessingml" in r.headers["content-type"]


def test_apply_unknown_resume_404(client):
    r = client.post("/api/tailor/apply", json={"resume_id": "nope", "suggestions": [], "format": "pdf"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /suggestions — tailor LangGraph (mocked at graph boundary)
# ---------------------------------------------------------------------------

def test_suggestions_happy(client, resume_id, valid_jd, mocker):
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value={
        "suggestions": [{"section": "Summary", "original": "old", "suggested": "new", "id": 1}],
        "project_names": [],
        "missing_keywords": ["kafka"],
    })
    mocker.patch("app.api.tailor.compiled_tailor_graph", fake_graph)

    r = client.post("/api/tailor/suggestions", json={"resume_id": resume_id, "jd_text": valid_jd})
    assert r.status_code == 200
    body = r.json()
    assert body["resume_id"] == resume_id
    assert "Summary" in body["sections"]
    assert body["jd_missing_keywords"] == ["kafka"]


def test_suggestions_empty_jd_400(client, resume_id):
    r = client.post("/api/tailor/suggestions", json={"resume_id": resume_id, "jd_text": "   "})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# /chat — copilot chat graph (mocked at graph boundary)
# ---------------------------------------------------------------------------

def test_chat_happy(client, resume_id, valid_jd, mocker):
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value={
        "suggestions": [],
        "directives": [],
        "response": "Done.",
    })
    mocker.patch("app.core.tailor_chat_graph.compiled_tailor_chat_graph", fake_graph)

    r = client.post(
        "/api/tailor/chat",
        json={"resume_id": resume_id, "jd_text": valid_jd, "user_prompt": "tailor my summary"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "Done."
    assert "suggestions" in body and "directives" in body


def test_chat_empty_prompt_400(client, resume_id, valid_jd):
    r = client.post(
        "/api/tailor/chat",
        json={"resume_id": resume_id, "jd_text": valid_jd, "user_prompt": "  "},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# /ats-check — rule-based (LLM filter mocked via get_llm_client)
# ---------------------------------------------------------------------------

def test_ats_check_happy(client, resume_id, valid_jd):
    r = client.post("/api/tailor/ats-check", json={"resume_id": resume_id, "jd_text": valid_jd})
    assert r.status_code == 200
    body = r.json()
    for key in ("parse_score", "keyword_score", "section_recognition", "suggestions"):
        assert key in body, f"missing {key}"


# ---------------------------------------------------------------------------
# Interactive single-shot edit endpoints
# ---------------------------------------------------------------------------

def test_regenerate_happy(client, valid_jd, mocker):
    mocker.patch("app.api.tailor.regenerate_one_suggestion", new=AsyncMock(return_value="A fresh alternative bullet."))
    r = client.post(
        "/api/tailor/regenerate",
        json={"jd_text": valid_jd, "section": "Experience", "original": "did stuff", "previous_suggested": "did things"},
    )
    assert r.status_code == 200
    assert r.json()["suggested"] == "A fresh alternative bullet."


def test_regenerate_empty_jd_400(client):
    r = client.post(
        "/api/tailor/regenerate",
        json={"jd_text": "  ", "section": "Experience", "original": "x", "previous_suggested": "y"},
    )
    assert r.status_code == 400


def test_chat_line_happy(client, resume_id, valid_jd, mocker):
    mocker.patch("app.core.llm_chat.chat_improve_line", new=AsyncMock(return_value="Rewritten, metrics-driven line."))
    r = client.post(
        "/api/tailor/chat-line",
        json={"resume_id": resume_id, "jd_text": valid_jd, "section": "Experience",
              "original_line": "led a team", "user_prompt": "add metrics"},
    )
    assert r.status_code == 200
    assert r.json()["rewritten"] == "Rewritten, metrics-driven line."


def test_chat_line_empty_prompt_400(client, resume_id, valid_jd):
    r = client.post(
        "/api/tailor/chat-line",
        json={"resume_id": resume_id, "jd_text": valid_jd, "section": "Experience",
              "original_line": "led a team", "user_prompt": "  "},
    )
    assert r.status_code == 400


def test_chat_entry_happy(client, resume_id, valid_jd, mocker):
    mocker.patch("app.core.llm_chat.chat_improve_entry", new=AsyncMock(return_value=["bullet one", "bullet two"]))
    r = client.post(
        "/api/tailor/chat-entry",
        json={"resume_id": resume_id, "jd_text": valid_jd, "section": "Experience", "entry_index": 0,
              "original_bullets": ["a", "b"], "header_context": {"title": "Dev"}, "user_prompt": "tighten"},
    )
    assert r.status_code == 200
    assert r.json()["rewritten_bullets"] == ["bullet one", "bullet two"]


def test_chat_entry_empty_bullets_400(client, resume_id, valid_jd):
    r = client.post(
        "/api/tailor/chat-entry",
        json={"resume_id": resume_id, "jd_text": valid_jd, "section": "Experience", "entry_index": 0,
              "original_bullets": [], "header_context": {}, "user_prompt": "tighten"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Skills + projects generation
# ---------------------------------------------------------------------------

def test_generate_skills_happy(client, resume_id, valid_jd, mocker):
    mocker.patch(
        "app.api.tailor.generate_skills_from_tailored",
        new=AsyncMock(return_value={"skills": [{"category": "Languages", "skills": ["Python", "Go"]}]}),
    )
    r = client.post("/api/tailor/generate-skills", json={"resume_id": resume_id, "jd_text": valid_jd})
    assert r.status_code == 200
    assert r.json()["skills"][0]["category"] == "Languages"


def test_generate_skills_empty_jd_400(client, resume_id):
    r = client.post("/api/tailor/generate-skills", json={"resume_id": resume_id, "jd_text": "  "})
    assert r.status_code == 400


def test_refresh_skills_happy(client, resume_id, valid_jd, mocker):
    mocker.patch("app.api.tailor.tailor_skills", new=AsyncMock(return_value=[]))
    mocker.patch("app.api.tailor.extract_jd_hard_requirements", new=AsyncMock(return_value={"required_skills_hard": []}))
    r = client.post("/api/tailor/refresh-skills", json={"resume_id": resume_id, "jd_text": valid_jd})
    assert r.status_code == 200
    body = r.json()
    assert "suggestions" in body and "next_id" in body


def test_generate_projects_happy(client, resume_id, valid_jd, mocker):
    mocker.patch("app.core.llm_synthesis.analyze_jd_for_projects", new=AsyncMock(return_value={"focus_areas": ["streaming"]}))
    mocker.patch(
        "app.core.llm_synthesis.synthesize_projects",
        new=AsyncMock(return_value=[{"name": "Realtime Pipeline", "tech": "Kafka", "bullets": ["Built streaming ingestion"]}]),
    )
    mocker.patch("app.api.tailor.humanize_project_bullets", new=AsyncMock(side_effect=lambda projects, **kw: projects))
    mocker.patch("app.api.tailor.llm_clean_tech_field", new=AsyncMock(side_effect=lambda t: t))

    r = client.post("/api/tailor/generate-projects", json={"resume_id": resume_id, "jd_text": valid_jd, "count": 1})
    assert r.status_code == 200
    body = r.json()
    assert "projects" in body and "jd_analysis" in body


def test_generate_projects_empty_jd_400(client, resume_id):
    r = client.post("/api/tailor/generate-projects", json={"resume_id": resume_id, "jd_text": "  "})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Additional coverage — read-only / render
# ---------------------------------------------------------------------------

def test_sample_preview_bad_template_falls_back(client):
    # _resolve_template_id collapses unknown ids to "standard" -> still 200.
    r = client.get("/api/tailor/sample-preview?template_id=bogus")
    assert r.status_code == 200
    assert "html" in r.json()


def test_preview_forwards_density_and_pages(client, resume_id, mocker):
    spy = mocker.patch("app.api.tailor.render_html", return_value="<html>x</html>")
    r = client.post(
        "/api/tailor/preview",
        json={"resume_id": resume_id, "suggestions": [], "template_id": "standard",
              "layout_density": "compact", "target_pages": 2},
    )
    assert r.status_code == 200
    assert spy.call_args.kwargs["layout_density"] == "compact"
    assert spy.call_args.kwargs["target_pages"] == 2


def test_apply_invalid_format_422(client, resume_id):
    r = client.post("/api/tailor/apply", json={"resume_id": resume_id, "suggestions": [], "format": "txt"})
    assert r.status_code == 422  # Literal["pdf","docx"] rejects at validation


# ---------------------------------------------------------------------------
# /suggestions — bucketing, intensity, thread cache
# ---------------------------------------------------------------------------

def _fake_graph(suggestions=None, project_names=None, missing=None):
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value={
        "suggestions": suggestions or [],
        "project_names": project_names or [],
        "missing_keywords": missing or [],
    })
    return fake


def test_suggestions_only_non_empty_sections(client, resume_id, valid_jd, mocker):
    from app.api.tailor import _SUGGESTIONS_CACHE
    _SUGGESTIONS_CACHE.clear()
    fake = _fake_graph(suggestions=[
        {"section": "Summary", "original": "a", "suggested": "b", "id": 1},
        {"section": "Skills", "original": "c", "suggested": "d", "id": 2},
    ], project_names=["P"])
    mocker.patch("app.api.tailor.compiled_tailor_graph", fake)
    r = client.post("/api/tailor/suggestions", json={"resume_id": resume_id, "jd_text": valid_jd})
    body = r.json()
    assert set(body["sections"].keys()) == {"Summary", "Skills"}
    assert body["project_names"] == ["P"]


@pytest.mark.parametrize("intensity,expected", [("aggressive", 2), ("balanced", 1), ("light", 1)])
def test_suggestions_intensity_sets_max_iterations(client, resume_id, valid_jd, mocker, intensity, expected):
    from app.api.tailor import _SUGGESTIONS_CACHE
    _SUGGESTIONS_CACHE.clear()
    fake = _fake_graph()
    mocker.patch("app.api.tailor.compiled_tailor_graph", fake)
    client.post("/api/tailor/suggestions",
                json={"resume_id": resume_id, "jd_text": valid_jd, "intensity": intensity})
    assert fake.ainvoke.call_args.args[0]["max_iterations"] == expected


def test_suggestions_thread_cache_hit(client, resume_id, valid_jd, mocker):
    from app.api.tailor import _SUGGESTIONS_CACHE
    _SUGGESTIONS_CACHE.clear()
    fake = _fake_graph()
    mocker.patch("app.api.tailor.compiled_tailor_graph", fake)
    body = {"resume_id": resume_id, "jd_text": valid_jd}
    client.post("/api/tailor/suggestions", json=body)
    client.post("/api/tailor/suggestions", json=body)
    assert fake.ainvoke.call_count == 1  # second served from _SUGGESTIONS_CACHE


# ---------------------------------------------------------------------------
# /chat — directives + 404
# ---------------------------------------------------------------------------

def test_chat_directives_passthrough(client, resume_id, valid_jd, mocker):
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value={
        "suggestions": [], "directives": [{"type": "undo_last"}], "response": "ok",
    })
    mocker.patch("app.core.tailor_chat_graph.compiled_tailor_chat_graph", fake)
    r = client.post("/api/tailor/chat",
                    json={"resume_id": resume_id, "jd_text": valid_jd, "user_prompt": "undo"})
    assert r.json()["directives"] == [{"type": "undo_last"}]


def test_chat_unknown_resume_404(client, valid_jd):
    r = client.post("/api/tailor/chat",
                    json={"resume_id": "nope", "jd_text": valid_jd, "user_prompt": "hi"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Interactive edits — extra validation + 404
# ---------------------------------------------------------------------------

def test_regenerate_empty_original_400(client, valid_jd):
    r = client.post("/api/tailor/regenerate",
                    json={"jd_text": valid_jd, "section": "Experience", "original": "  ", "previous_suggested": "y"})
    assert r.status_code == 400


def test_chat_line_empty_line_400(client, resume_id, valid_jd):
    r = client.post("/api/tailor/chat-line",
                    json={"resume_id": resume_id, "jd_text": valid_jd, "section": "Experience",
                          "original_line": "   ", "user_prompt": "add metrics"})
    assert r.status_code == 400


def test_ats_check_unknown_resume_404(client, valid_jd):
    r = client.post("/api/tailor/ats-check", json={"resume_id": "nope", "jd_text": valid_jd})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Skills generation — intensity override + add-mode drop
# ---------------------------------------------------------------------------

def test_generate_skills_section_intensity_overrides_global(client, resume_id, valid_jd, mocker):
    captured = {}

    async def _fake(**kwargs):
        captured.update(kwargs)
        return {"skills": []}

    mocker.patch("app.api.tailor.generate_skills_from_tailored", new=_fake)
    r = client.post("/api/tailor/generate-skills",
                    json={"resume_id": resume_id, "jd_text": valid_jd,
                          "intensity": "light", "section_intensities": {"skills": "aggressive"}})
    assert r.status_code == 200
    assert captured["intensity"] == "aggressive"


def test_refresh_skills_drops_add_mode_and_reassigns_ids(client, resume_id, valid_jd, mocker):
    mocker.patch("app.api.tailor.tailor_skills", new=AsyncMock(return_value=[
        {"mode": "add_skill", "skill": "x", "id": 99},
        {"mode": "rename", "from": "a", "to": "b", "id": 98},
    ]))
    mocker.patch("app.api.tailor.extract_jd_hard_requirements",
                 new=AsyncMock(return_value={"required_skills_hard": []}))
    mocker.patch("app.core.tailor_orchestrator._derive_skill_additions", return_value=[])
    r = client.post("/api/tailor/refresh-skills",
                    json={"resume_id": resume_id, "jd_text": valid_jd, "next_id": 100})
    body = r.json()
    assert "add_skill" not in [s.get("mode") for s in body["suggestions"]]
    assert body["suggestions"][0]["id"] == 100
    assert body["next_id"] == 101


def test_generate_projects_count_zero_fails_validation(client, resume_id, valid_jd, mocker):
    # F3 check: count=0 should fail pydantic validation (ge=1)
    r = client.post("/api/tailor/generate-projects",
                    json={"resume_id": resume_id, "jd_text": valid_jd, "count": 0})
    assert r.status_code == 422
