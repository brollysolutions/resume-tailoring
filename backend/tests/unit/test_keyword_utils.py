import pytest
from app.core.keyword_utils import _significant_tokens

def test_significant_tokens_basic():
    text = "Expert in Python, React, and FastAPI development."
    tokens = _significant_tokens(text)
    assert "python" in tokens
    assert "react" in tokens
    assert "fastapi" in tokens

def test_significant_tokens_scrubbing():
    # Dates and locations should be scrubbed by spaCy (NER)
    text = "Worked in New York during 2023."
    tokens = _significant_tokens(text)
    # "New York" is GPE, "2023" is DATE
    assert "new york" not in tokens
    assert "2023" not in tokens

def test_significant_tokens_empty():
    assert _significant_tokens("") == set()
    assert _significant_tokens(None) == set()
