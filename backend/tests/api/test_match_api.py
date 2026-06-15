from unittest.mock import MagicMock


def test_match_happy(client, resume_id, valid_jd):
    r = client.post("/api/match/", json={"resume_id": resume_id, "jd_text": valid_jd})
    assert r.status_code == 200
    body = r.json()
    for key in ("score", "breakdown", "section_scores", "ceiling", "active_weights"):
        assert key in body, f"missing {key}"
    assert isinstance(body["score"], int)


def test_match_full_response_shape(client, resume_id, valid_jd):
    r = client.post("/api/match/", json={"resume_id": resume_id, "jd_text": valid_jd})
    body = r.json()
    # Fields beyond the back-compat core that the frontend tabs consume.
    for key in ("section_features", "diagnosis", "gap_analysis"):
        assert key in body, f"missing {key}"
    assert 0 <= body["score"] <= 100
    aw = body["active_weights"]
    assert set(aw) == {"w_kw", "w_skill", "w_ngram", "w_edu", "w_sen", "w_cos"}
    assert 95 <= sum(aw.values()) <= 105  # rounded percentages ~ 100


def test_match_long_jd_too_few_tokens_400(client, resume_id):
    # >=200 chars but only one distinct significant token -> second _validate_jd branch.
    r = client.post("/api/match/", json={"resume_id": resume_id, "jd_text": "data " * 60})
    assert r.status_code == 400
    assert "meaningful keywords" in r.json()["detail"]


def test_match_empty_resume_id_404(client, valid_jd):
    r = client.post("/api/match/", json={"resume_id": "", "jd_text": valid_jd})
    assert r.status_code == 404


def test_match_corrupt_stored_json_500(client, resume_id, valid_jd, fake_qdrant):
    bad = MagicMock()
    bad.payload = {"resume_json": "{not valid json", "text": "x", "file_ext": ".pdf"}
    bad.vector = [0.1] * 768
    fake_qdrant.retrieve.side_effect = lambda **kw: [bad]
    r = client.post("/api/match/", json={"resume_id": resume_id, "jd_text": valid_jd})
    assert r.status_code == 500


def test_match_unknown_resume_404(client, valid_jd):
    r = client.post("/api/match/", json={"resume_id": "nope", "jd_text": valid_jd})
    assert r.status_code == 404


def test_match_short_jd_400(client, resume_id):
    r = client.post("/api/match/", json={"resume_id": resume_id, "jd_text": "too short to score"})
    assert r.status_code == 400


def test_match_tailored_happy(client, resume_id, valid_jd):
    r = client.post(
        "/api/match/tailored",
        json={"resume_id": resume_id, "jd_text": valid_jd, "accepted_suggestions": [], "new_projects": []},
    )
    assert r.status_code == 200
    body = r.json()
    assert "original" in body and "tailored" in body and "delta" in body
    assert "improvement_plan" in body["tailored"]


def test_match_tailored_delta_and_plan_shape(client, resume_id, valid_jd):
    r = client.post(
        "/api/match/tailored",
        json={"resume_id": resume_id, "jd_text": valid_jd, "accepted_suggestions": [], "new_projects": []},
    )
    body = r.json()
    assert body["delta"] == body["tailored"]["score"] - body["original"]["score"]
    plan = body["tailored"]["improvement_plan"]
    for key in ("current_score", "achievable_ceiling", "actions", "blockers"):
        assert key in plan, f"missing {key}"


def test_match_tailored_original_snapshot_is_stable(client, resume_id, valid_jd):
    # Second identical call must reuse the in-process original snapshot -> same original score.
    body = {"resume_id": resume_id, "jd_text": valid_jd, "accepted_suggestions": [], "new_projects": []}
    first = client.post("/api/match/tailored", json=body).json()
    second = client.post("/api/match/tailored", json=body).json()
    assert first["original"]["score"] == second["original"]["score"]


def test_match_tailored_short_jd_400(client, resume_id):
    r = client.post("/api/match/tailored", json={"resume_id": resume_id, "jd_text": "too short"})
    assert r.status_code == 400


def test_match_tailored_unknown_resume_404(client, valid_jd):
    r = client.post("/api/match/tailored", json={"resume_id": "nope", "jd_text": valid_jd})
    assert r.status_code == 404


def test_match_guidance_happy(client, resume_id, valid_jd):
    r = client.post(
        "/api/match/guidance",
        json={"resume_id": resume_id, "jd_text": valid_jd, "section_scores": {"Experience": 50}},
    )
    assert r.status_code == 200
    body = r.json()
    assert "sections" in body and "blockers" in body


def test_match_guidance_short_jd_400(client, resume_id):
    r = client.post("/api/match/guidance", json={"resume_id": resume_id, "jd_text": "short"})
    assert r.status_code == 400


def test_match_guidance_unknown_resume_404(client, valid_jd):
    r = client.post("/api/match/guidance", json={"resume_id": "nope", "jd_text": valid_jd})
    assert r.status_code == 404


def test_match_guidance_empty_sections_skips_llm(client, resume_id, valid_jd, patch_llm):
    # No low sections + clean ceiling -> both helpers short-circuit, zero LLM cost.
    r = client.post(
        "/api/match/guidance",
        json={"resume_id": resume_id, "jd_text": valid_jd, "section_scores": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sections"] == {} and body["blockers"] == []
    patch_llm.assert_not_called()
