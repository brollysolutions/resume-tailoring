import pytest
import json
from app.core.llm_helpers import _looks_like_meta, _looks_like_graft, tailor_experience, tailor_summary

def test_looks_like_meta_positive():
    meta_texts = [
        "This aligns with the JD's requirement of back end web development.",
        "Add a bullet that demonstrates your Python skills which aligns with the job description.",
        "This bullet can be added to show experience with Docker.",
        "suggested to include GCP experience to support jd requirements.",
        "However, this experience with backend aligns with JD.",
    ]
    for text in meta_texts:
        assert _looks_like_meta(text) is True, f"Failed on: {text}"

def test_looks_like_meta_negative():
    normal_texts = [
        "Built and maintained scalable Python web applications using FastAPI and PostgreSQL.",
        "Gathered user requirements and designed the software architecture.",
        "Led a team of 4 software developers to deliver projects on time.",
        "Designed and implemented high-performance REST APIs.",
        "",
        None,
    ]
    for text in normal_texts:
        assert _looks_like_meta(text) is False, f"Failed on: {text}"

def test_looks_like_graft_positive():
    grafts = [
        "Using knowledge of X, I architected and deployed backend web applications.",
        "Improving website performance and mobile responsiveness, I optimized application performance.",
        "Collaborated within a cross functional team to implement and optimize front end features, our team shipped it.",
        "I built a Python script.",
        "Designed the system, which was our core focus.",
        "Managed the migration for me and my colleagues.",
    ]
    for text in grafts:
        assert _looks_like_graft(text) is True, f"Failed to detect graft: {text}"

def test_looks_like_graft_negative():
    normal = [
        "Architected and deployed backend web applications.",
        "Optimized website performance and mobile responsiveness.",
        "Collaborated with cross-functional teams to implement front-end features.",
        "Implemented high-performance REST APIs using Django.",
    ]
    for text in normal:
        assert _looks_like_graft(text) is False, f"Failed: detected false graft: {text}"

@pytest.mark.asyncio
async def test_tailor_experience_rejects_graft(mock_llm_client):
    mock_llm_client.return_value = json.dumps({
        "suggestions": [
            {
                "section": "Experience",
                "original": "Original bullet 1",
                "suggested": "Using knowledge of React, I built the UI.",
                "mode": "replace",
                "reasoning": "Reason 1"
            },
            {
                "section": "Experience",
                "original": "Original bullet 2",
                "suggested": "Built the clean simple-past UI.",
                "mode": "replace",
                "reasoning": "Reason 2"
            },
            {
                "section": "Experience",
                "original": "Original bullet 3",
                "suggested": "I developed a new feature.",
                "mode": "replace",
                "reasoning": "Reason 3"
            }
        ]
    })

    experience = [
        {
            "title": "Developer",
            "company": "Tech Corp",
            "bullets": ["Original bullet 1", "Original bullet 2", "Original bullet 3"]
        }
    ]

    res = await tailor_experience(experience, "target JD", keywords_to_inject=["React"])
    # "Using knowledge..." is a gerund graft -> should be dropped
    # "I developed..." contains first person -> should be dropped
    # "Built the clean..." -> should be kept
    assert len(res) == 1
    assert res[0]["suggested"] == "Built the clean simple past UI."

@pytest.mark.asyncio
async def test_tailor_summary_keeps_first_person(mock_llm_client):
    mock_llm_client.return_value = json.dumps({
        "suggestions": [
            {
                "section": "Summary",
                "original": "Original summary",
                "suggested": "I am an experienced Python developer.",
                "mode": "replace",
                "reasoning": "Reason 1"
            }
        ]
    })

    res = await tailor_summary("Original summary", "target JD", keywords_to_inject=["Python"])
    assert len(res) == 1
    assert res[0]["suggested"] == "I am an experienced Python developer."
