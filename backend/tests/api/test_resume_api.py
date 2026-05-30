from unittest.mock import AsyncMock


def test_upload_pdf_happy(client, mocker, sample_resume):
    mocker.patch("app.api.resume._extract_text_from_pdf", return_value=("raw resume text", {}))
    mocker.patch("app.api.resume.extract_resume", new=AsyncMock(return_value=sample_resume))
    mocker.patch("app.api.resume.generate_keywords", new=AsyncMock(return_value=(["Backend Engineer"], ["Python"])))

    files = {"file": ("resume.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
    r = client.post("/api/resume/upload", files=files)

    assert r.status_code == 200
    body = r.json()
    assert "resume_id" in body
    assert body["keywords"] == ["Backend Engineer"]
    assert body["stack"] == ["Python"]

    assert body["file_ext"] == ".pdf"


def test_upload_rejects_unsupported_extension(client):
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    r = client.post("/api/resume/upload", files=files)
    assert r.status_code == 400


def test_upload_too_large_413(client):
    big = b"x" * (10 * 1024 * 1024 + 1)  # just over the 10 MB cap
    files = {"file": ("resume.pdf", big, "application/pdf")}
    r = client.post("/api/resume/upload", files=files)
    assert r.status_code == 413


def test_upload_docx_happy(client, mocker, sample_resume):
    mocker.patch("app.api.resume._extract_text_from_docx", return_value=("raw docx text", {}))
    mocker.patch("app.api.resume.extract_resume", new=AsyncMock(return_value=sample_resume))
    mocker.patch("app.api.resume.generate_keywords", new=AsyncMock(return_value=(["Backend Engineer"], ["Python"])))
    files = {"file": ("resume.docx", b"PK\x03\x04 fake docx",
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    r = client.post("/api/resume/upload", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["file_ext"] == ".docx"
    assert body["stack"] == ["Python"]


def test_scaffold_creates_resume(client):
    r = client.post("/api/resume/scaffold", json={"template_id": "standard"})
    assert r.status_code == 200
    body = r.json()
    assert "resume_id" in body
    assert body["template_id"] == "standard"
    assert "stack" in body
    assert isinstance(body["stack"], list)



def test_get_text_known(client, resume_id):
    r = client.get(f"/api/resume/{resume_id}/text")
    assert r.status_code == 200
    assert r.json()["resume_id"] == resume_id


def test_get_text_unknown_404(client):
    r = client.get("/api/resume/does-not-exist/text")
    assert r.status_code == 404


def test_get_json_known(client, resume_id, mocker):
    # project tech triggers llm_clean_tech_field; keep it deterministic.
    mocker.patch("app.api.resume.llm_clean_tech_field", new=AsyncMock(side_effect=lambda t: t))
    r = client.get(f"/api/resume/{resume_id}/json")
    assert r.status_code == 200
    assert "experience" in r.json()


def test_get_json_unknown_404(client):
    r = client.get("/api/resume/does-not-exist/json")
    assert r.status_code == 404


def test_patch_sections(client, resume_id):
    r = client.patch(
        f"/api/resume/{resume_id}/sections",
        json={"hidden_sections": ["projects"], "section_order": ["experience", "skills"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["hidden_sections"] == ["projects"]
    assert body["section_order"] == ["experience", "skills"]


def test_patch_sections_partial_body(client, resume_id):
    # Only hidden_sections supplied; section_order still echoed back as a list.
    r = client.patch(f"/api/resume/{resume_id}/sections", json={"hidden_sections": ["awards"]})
    assert r.status_code == 200
    body = r.json()
    assert body["hidden_sections"] == ["awards"]
    assert isinstance(body["section_order"], list)


def test_patch_sections_unknown_404(client):
    r = client.patch("/api/resume/nope/sections", json={"hidden_sections": []})
    assert r.status_code == 404
