"""Fixtures for HTTP-layer endpoint tests.

These patch the three external boundaries — Qdrant storage, the embedding
model, and the LLM client — so each endpoint test exercises the real FastAPI
request/response path without touching the network, Redis, or native deps.

Scoped to tests/api/ so the existing unit/integration suites are unaffected.

Patch-target notes (see the binding gotcha in the plan):
- ``init_qdrant`` is bound at module top in match.py and resume.py
  (``from app.core.vector_db import init_qdrant``) but imported function-locally
  in tailor.py. So we patch it in every namespace that can reach it.
- ``get_llm_client`` is the single chokepoint every ``_chat`` call routes through;
  patching it intercepts all LLM traffic at one point.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app

KNOWN_RESUME_ID = "known-resume-id"
EMBED_DIM = 768


@pytest.fixture
def client():
    # No context manager -> the app lifespan (embedding preload + auto-calibrator
    # loop) never runs, keeping tests fast and side-effect free.
    return TestClient(app)


@pytest.fixture
def resume_id():
    return KNOWN_RESUME_ID


@pytest.fixture
def valid_jd():
    """A JD that clears _validate_jd (>=200 chars and >=30 significant tokens)."""
    return (
        "We are seeking a Senior Backend Engineer with strong experience in "
        "Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS, "
        "microservices, REST APIs, GraphQL, distributed systems, asynchronous "
        "programming, message queues, Kafka, RabbitMQ, CICD pipelines, automated "
        "testing, monitoring, observability, scalability, performance optimization, "
        "database design, caching strategies, authentication, authorization, "
        "security, and agile development. The ideal candidate has built production "
        "services handling millions of requests per day across multiple regions."
    )


def _resume_point(resume):
    pt = MagicMock()
    pt.payload = {
        "resume_json": resume.model_dump_json(),
        "text": "Experienced software engineer Python React backend systems.",
        "original_filename": "resume.pdf",
        "file_ext": ".pdf",
        "original_path": "",
    }
    pt.vector = [0.1] * EMBED_DIM
    return pt


@pytest.fixture
def fake_qdrant(sample_resume):
    """MagicMock Qdrant client: returns sample_resume for KNOWN_RESUME_ID only."""
    qc = MagicMock()
    point = _resume_point(sample_resume)

    def _retrieve(collection_name=None, ids=None, **kwargs):
        if ids and KNOWN_RESUME_ID in ids:
            return [point]
        return []

    qc.retrieve.side_effect = _retrieve
    qc.search.return_value = []
    qc.scroll.return_value = ([], None)
    qc.query_points.return_value = MagicMock(points=[])
    return qc


@pytest.fixture(autouse=True)
def patch_storage(mocker, fake_qdrant):
    init = MagicMock(return_value=fake_qdrant)
    mocker.patch("app.core.vector_db.init_qdrant", init)
    mocker.patch("app.api.match.init_qdrant", init)
    mocker.patch("app.api.resume.init_qdrant", init)
    mocker.patch("app.core.vector_db.get_qdrant_client", return_value=fake_qdrant)
    return fake_qdrant


@pytest.fixture(autouse=True)
def patch_embedding(mocker):
    one = AsyncMock(return_value=[0.1] * EMBED_DIM)
    many = AsyncMock(side_effect=lambda texts: [[0.1] * EMBED_DIM for _ in texts])
    mocker.patch("app.core.vector_db.get_embedding", one)
    mocker.patch("app.core.vector_db.get_embeddings", many)
    mocker.patch("app.api.match.get_embedding", one)
    mocker.patch("app.api.match.get_embeddings", many)
    mocker.patch("app.api.resume.get_embedding", one)


def _llm_response(content: str):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture(autouse=True)
def patch_llm(mocker):
    """Intercept every _chat() call at the single get_llm_client chokepoint."""
    fake = MagicMock()
    fake.chat.completions.create = AsyncMock(
        return_value=_llm_response('{"actionable": [], "suggestions": []}')
    )
    mocker.patch("app.core.llm_client.get_llm_client", return_value=fake)
    return fake.chat.completions.create


@pytest.fixture(autouse=True)
def patch_cache(mocker):
    """Force cache misses so endpoints never block on Redis."""
    miss = AsyncMock(return_value=None)
    noop = AsyncMock(return_value=None)
    for mod in ("app.api.match", "app.core.llm_client"):
        mocker.patch(f"{mod}.get_cached_value", miss)
        mocker.patch(f"{mod}.set_cached_value", noop)


@pytest.fixture(autouse=True)
def patch_data_logs(mocker):
    """Neutralize every jsonl/event writer so api tests never mutate the
    committed backend/data/ logs (F2 — see docs/TEST_FINDINGS.md).

    Each writer is patched in the module that *calls* it (the `from x import y`
    binding gotcha noted in this file's header). log_suggestion_event is imported
    function-locally at each call site, so patching it at the source module
    (implicit_labeler) covers match.py and tailor.py alike.
    """
    mocker.patch("app.api.match._log_section_delta", MagicMock())
    mocker.patch("app.api.match_logic.hybrid_scorer._log_score_event", MagicMock())
    mocker.patch("app.api.match_logic.section_scorer._log_section_event", MagicMock())
    mocker.patch("app.core.implicit_labeler.log_suggestion_event", MagicMock())
    mocker.patch("app.api.resume._log_upload_event", MagicMock())
