from unittest.mock import AsyncMock, MagicMock
import pytest

from app.core.rag_service import RAGService, _split_jd_clauses
from app.models.resume_schema import Resume


# ---------------------------------------------------------------------------
# _create_chunks — per-bullet chunking
# ---------------------------------------------------------------------------

def test_create_chunks_emits_per_bullet():
    resume = Resume(
        experience=[{
            "title": "Engineer",
            "company": "Acme",
            "bullets": ["Built API", "Scaled DB", "Led team"],
        }],
        projects=[{
            "name": "Widget",
            "tech": "Python",
            "bullets": ["Wrote tests", "Deployed to AWS"],
        }],
    )
    chunks = RAGService._create_chunks(resume)

    exp_chunks = [c for c in chunks if c["metadata"]["section"] == "Experience"]
    proj_chunks = [c for c in chunks if c["metadata"]["section"] == "Projects"]

    # 1 entry-summary + 3 bullet chunks
    assert len(exp_chunks) == 4
    # 1 entry-summary + 2 bullet chunks
    assert len(proj_chunks) == 3

    exp_bullets = [c for c in exp_chunks if "bullet_index" in c["metadata"]]
    assert len(exp_bullets) == 3
    assert exp_bullets[0]["metadata"]["bullet_index"] == 0
    assert exp_bullets[2]["metadata"]["bullet_index"] == 2

    assert "Built API" in exp_bullets[0]["text"]
    assert "Engineer" in exp_bullets[0]["text"]
    assert "Acme" in exp_bullets[0]["text"]


def test_create_chunks_entry_summary_contains_all_bullets():
    resume = Resume(
        experience=[{
            "title": "Dev",
            "company": "Corp",
            "bullets": ["Did X", "Did Y"],
        }],
    )
    chunks = RAGService._create_chunks(resume)
    summary = next(
        c for c in chunks
        if c["metadata"]["section"] == "Experience" and "bullet_index" not in c["metadata"]
    )
    assert "Did X" in summary["text"]
    assert "Did Y" in summary["text"]


def test_create_chunks_no_bullets_emits_only_entry_summary():
    resume = Resume(
        experience=[{"title": "Dev", "company": "Corp", "bullets": []}],
    )
    chunks = RAGService._create_chunks(resume)
    exp_chunks = [c for c in chunks if c["metadata"]["section"] == "Experience"]
    assert len(exp_chunks) == 1
    assert "bullet_index" not in exp_chunks[0]["metadata"]


def test_create_chunks_multi_entry_bullet_indices_independent():
    resume = Resume(
        experience=[
            {"title": "Dev", "company": "A", "bullets": ["X", "Y"]},
            {"title": "Lead", "company": "B", "bullets": ["Z"]},
        ],
    )
    chunks = RAGService._create_chunks(resume)
    exp0_bullets = [c for c in chunks if c["metadata"]["section"] == "Experience"
                    and c["metadata"]["entry_index"] == 0 and "bullet_index" in c["metadata"]]
    exp1_bullets = [c for c in chunks if c["metadata"]["section"] == "Experience"
                    and c["metadata"]["entry_index"] == 1 and "bullet_index" in c["metadata"]]
    assert len(exp0_bullets) == 2
    assert len(exp1_bullets) == 1
    assert exp0_bullets[0]["metadata"]["bullet_index"] == 0
    assert exp1_bullets[0]["metadata"]["bullet_index"] == 0


# ---------------------------------------------------------------------------
# _split_jd_clauses — role detection
# ---------------------------------------------------------------------------

def test_split_jd_clauses_role_detection():
    jd = (
        "About us\n"
        "We build great products for customers.\n"
        "\n"
        "Responsibilities:\n"
        "- Design and build scalable distributed services\n"
        "- Write clean maintainable production code\n"
        "\n"
        "Requirements:\n"
        "- 3+ years Python experience required\n"
        "- Strong SQL skills and database design\n"
        "\n"
        "Preferred qualifications:\n"
        "- Knowledge of Kubernetes and container orchestration\n"
    )
    clauses = _split_jd_clauses(jd)
    role_by_text = {c["text"]: c["role"] for c in clauses}

    assert role_by_text.get("- Design and build scalable distributed services") == "responsibility"
    assert role_by_text.get("- Write clean maintainable production code") == "responsibility"
    assert role_by_text.get("- 3+ years Python experience required") == "requirement"
    assert role_by_text.get("- Strong SQL skills and database design") == "requirement"
    assert role_by_text.get("- Knowledge of Kubernetes and container orchestration") == "qualification"


def test_split_jd_clauses_skips_short_lines():
    jd = "OK\nThis is a substantive line about Python skills required for the role"
    clauses = _split_jd_clauses(jd)
    texts = [c["text"] for c in clauses]
    assert "OK" not in texts
    assert any("Python" in t for t in texts)


def test_split_jd_clauses_default_role_is_requirement():
    jd = "We need an engineer with Python and SQL experience for the position."
    clauses = _split_jd_clauses(jd)
    assert all(c["role"] == "requirement" for c in clauses)


def test_split_jd_clauses_clause_index_monotonic():
    jd = "First substantive line here okay\nSecond substantive line here also\nThird line here too"
    clauses = _split_jd_clauses(jd)
    indices = [c["clause_index"] for c in clauses]
    assert indices == sorted(indices)


# ---------------------------------------------------------------------------
# RAGService.index_jd — idempotency + indexing
# ---------------------------------------------------------------------------

async def test_index_jd_idempotent(mocker):
    mock_client = MagicMock()
    mock_client.count.return_value = MagicMock(count=5)

    mocker.patch("app.core.rag_service.init_qdrant")
    mocker.patch("app.core.rag_service.get_qdrant_client", return_value=mock_client)
    mocker.patch("app.core.rag_service.get_embedding", new_callable=AsyncMock, return_value=[0.1] * 768)

    await RAGService.index_jd("abc123", "Python engineer required with strong SQL skills.")

    mock_client.upsert.assert_not_called()


async def test_index_jd_indexes_new_jd(mocker):
    mock_client = MagicMock()
    mock_client.count.return_value = MagicMock(count=0)

    mocker.patch("app.core.rag_service.init_qdrant")
    mocker.patch("app.core.rag_service.get_qdrant_client", return_value=mock_client)
    mocker.patch("app.core.rag_service.get_embedding", new_callable=AsyncMock, return_value=[0.1] * 768)

    jd = "We need a Python engineer with five years of experience and strong SQL skills."
    await RAGService.index_jd("def456", jd)

    mock_client.upsert.assert_called_once()
    points = mock_client.upsert.call_args[1]["points"]
    assert all(p.payload["jd_hash"] == "def456" for p in points)
    assert all("role" in p.payload for p in points)
    assert all("clause_index" in p.payload for p in points)


async def test_index_jd_proceeds_when_count_check_fails(mocker):
    """If the idempotency count check throws, indexing continues (non-fatal)."""
    mock_client = MagicMock()
    mock_client.count.side_effect = Exception("Qdrant unavailable")

    mocker.patch("app.core.rag_service.init_qdrant")
    mocker.patch("app.core.rag_service.get_qdrant_client", return_value=mock_client)
    mocker.patch("app.core.rag_service.get_embedding", new_callable=AsyncMock, return_value=[0.1] * 768)

    jd = "We need a Python engineer with five years of experience and strong SQL skills."
    await RAGService.index_jd("err999", jd)

    # Falls through to upsert despite the count error
    mock_client.upsert.assert_called_once()
