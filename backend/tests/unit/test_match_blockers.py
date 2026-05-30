"""Unit tests for explain_match_blockers (prompt-driven edge-case coaching)."""
import json

from app.core.llm_helpers import explain_match_blockers


async def test_no_reasons_skips_llm(mock_llm_client):
    """Empty ceiling reasons -> [] with no LLM call (no cost on clean profiles)."""
    out = await explain_match_blockers("jd text", {"score": 100, "reasons": []})
    assert out == []
    mock_llm_client.assert_not_called()


async def test_none_ceiling_skips_llm(mock_llm_client):
    out = await explain_match_blockers("jd text", None)
    assert out == []
    mock_llm_client.assert_not_called()


async def test_blockers_parsed_with_kinds(mock_llm_client):
    mock_llm_client.return_value = json.dumps(
        {
            "blockers": [
                {"kind": "experience", "headline": "Experience gap", "detail": "You show ~2 yrs vs 5."},
                {"kind": "seniority", "headline": "Seniority gap", "detail": "Emphasize leadership scope."},
            ]
        }
    )
    out = await explain_match_blockers(
        "jd text",
        {
            "score": 45,
            "reasons": ["needs 5+ yrs (resume ~2)", "targets lead level"],
            "exp_required": 5,
            "exp_actual": 2,
        },
    )
    assert [b["kind"] for b in out] == ["experience", "seniority"]
    assert all(b["headline"] and b["detail"] for b in out)
    mock_llm_client.assert_called_once()


async def test_invalid_kind_dropped(mock_llm_client):
    mock_llm_client.return_value = json.dumps(
        {
            "blockers": [
                {"kind": "salary", "headline": "x", "detail": "y."},
                {"kind": "education", "headline": "Degree", "detail": "List your B.S."},
            ]
        }
    )
    out = await explain_match_blockers("jd", {"reasons": ["requires Bachelor degree"]})
    assert [b["kind"] for b in out] == ["education"]


async def test_duplicate_kind_deduped(mock_llm_client):
    mock_llm_client.return_value = json.dumps(
        {
            "blockers": [
                {"kind": "experience", "headline": "A", "detail": "first."},
                {"kind": "experience", "headline": "B", "detail": "second."},
            ]
        }
    )
    out = await explain_match_blockers("jd", {"reasons": ["needs 5+ yrs (resume ~2)"]})
    assert len(out) == 1
    assert out[0]["headline"] == "A"


async def test_malformed_json_returns_empty(mock_llm_client):
    mock_llm_client.return_value = "not json at all"
    out = await explain_match_blockers("jd", {"reasons": ["targets lead level"]})
    assert out == []
    assert mock_llm_client.call_count == 2  # initial + retry
