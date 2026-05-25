import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.resume_schema import Resume

@pytest.fixture
def mock_llm_client(mocker):
    """Mocks the LLM client responses."""
    # Patch where it is USED, not where it is DEFINED, because of 'from x import y'
    mock = mocker.patch("app.core.llm_helpers._chat", new_callable=AsyncMock)
    return mock

@pytest.fixture
def mock_embedding(mocker):
    """Mocks vector embedding generation."""
    mock = mocker.patch("app.core.vector_db.get_embedding", new_callable=AsyncMock)
    mock.return_value = [0.1] * 768
    return mock

@pytest.fixture
def mock_qdrant(mocker):
    """Mocks Qdrant client operations."""
    mock_client = MagicMock()
    mocker.patch("app.core.vector_db.init_qdrant", return_value=mock_client)
    mocker.patch("app.core.vector_db.get_qdrant_client", return_value=mock_client)
    return mock_client

@pytest.fixture
def sample_resume():
    """Provides a basic Resume object for testing."""
    return Resume(
        summary="Experienced software engineer with focus on Python and React.",
        experience=[{
            "title": "Senior Dev",
            "company": "Tech Corp",
            "bullets": ["Led a team of 5", "Implemented caching"]
        }],
        projects=[{
            "name": "E-commerce Site",
            "tech": "React, Node.js",
            "bullets": ["Built a responsive checkout page"]
        }],
        education=[{
            "institution": "Tech University",
            "degree": "B.S. in Computer Science",
            "details": ["Minor in Mathematics"]
        }],
        skills=[{"category": "Languages", "skills": ["Python", "JavaScript"]}]
    )
