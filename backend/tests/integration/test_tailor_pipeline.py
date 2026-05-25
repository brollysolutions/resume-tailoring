import pytest
import json
from app.core.tailor_orchestrator import generate_section_suggestions

async def test_generate_section_suggestions_parallel(mock_llm_client, sample_resume):
    # Mock LLM response for all 4 sections
    mock_llm_client.return_value = json.dumps({
        "suggestions": [{"original": "old", "suggested": "new", "reasoning": "better"}]
    })
    
    jd_text = "Looking for a Python developer with experience in React."
    
    result = await generate_section_suggestions(sample_resume, jd_text)
    
    # Verify we got suggestions for all sections
    assert "Summary" in result["sections"]
    assert "Experience" in result["sections"]
    assert "Projects" in result["sections"]
    assert "Education" in result["sections"]
    
    # Verify call count (should be 4)
    assert mock_llm_client.call_count == 4
