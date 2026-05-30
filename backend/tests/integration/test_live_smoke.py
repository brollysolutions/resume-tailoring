"""Opt-in live smoke tests — real embedding model + real LLM + real Qdrant.

These do NOT mock anything. They exercise the full stack the way docs/TESTING.md
§B does, but through the FastAPI app object (TestClient as a context manager so
the lifespan preloads the embedding model).

Skipped by default. To run:

    # PowerShell, from backend/, with Qdrant reachable and a provider key set:
    $env:RUN_LIVE = "1"
    pytest tests/integration/test_live_smoke.py -v

Requires:
  - RUN_LIVE=1
  - GROQ_API_KEY or OPENAI_API_KEY
  - A reachable Qdrant (QDRANT_HOST/QDRANT_PORT, default localhost:6334)
They are intentionally NOT wired into the default CI run.
"""
import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE") != "1"
    or not (os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")),
    reason="live smoke: set RUN_LIVE=1 with a provider key and Qdrant up",
)

# A substantial JD that clears _validate_jd (>=200 chars, >=30 significant tokens).
LIVE_JD = (
    "We are seeking a Senior Backend Engineer with strong experience in Python, "
    "FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS, microservices, REST APIs, "
    "GraphQL, distributed systems, asynchronous programming, message queues, Kafka, "
    "RabbitMQ, CI/CD pipelines, automated testing, monitoring, observability, "
    "scalability, performance optimization, database design, caching strategies, "
    "authentication, authorization, security, and agile development. The ideal "
    "candidate has built production services handling millions of requests per day."
)


@pytest.fixture(scope="module")
def live_client():
    from app.main import app
    # Context manager -> runs lifespan (embedding preload).
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def live_resume_id(live_client):
    r = live_client.post("/api/resume/scaffold", json={"template_id": "standard"})
    assert r.status_code == 200, r.text
    return r.json()["resume_id"]


def test_live_health(live_client):
    assert live_client.get("/health").json()["status"] == "ok"


def test_live_match(live_client, live_resume_id):
    r = live_client.post("/api/match/", json={"resume_id": live_resume_id, "jd_text": LIVE_JD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0 < body["score"] <= 100
    assert body["ceiling"] is not None
    assert isinstance(body["section_scores"], dict)


def test_live_match_tailored(live_client, live_resume_id):
    r = live_client.post(
        "/api/match/tailored",
        json={"resume_id": live_resume_id, "jd_text": LIVE_JD, "accepted_suggestions": [], "new_projects": []},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["delta"], int)
    assert body["delta"] == body["tailored"]["score"] - body["original"]["score"]


def test_live_suggestions(live_client, live_resume_id):
    r = live_client.post(
        "/api/tailor/suggestions",
        json={"resume_id": live_resume_id, "jd_text": LIVE_JD, "intensity": "balanced"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["suggestions"], list)
    assert "jd_missing_keywords" in body


def test_live_apply_pdf(live_client, live_resume_id):
    r = live_client.post(
        "/api/tailor/apply",
        json={"resume_id": live_resume_id, "suggestions": [], "format": "pdf", "template_id": "standard"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
