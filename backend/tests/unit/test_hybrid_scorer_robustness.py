import pytest
from pathlib import Path
from app.api.match_logic.hybrid_scorer import score_resume_against_jd, ScoreInputs, compute_signals
from app.core.sample_resume import build_sample_resume
from app.models.resume_schema import Resume

JD_DIR = Path(__file__).resolve().parents[1] / "data" / "jds"

@pytest.fixture
def sample_resume():
    return build_sample_resume()

def load_jd(filename: str) -> str:
    with open(JD_DIR / filename, "r", encoding="utf-8") as f:
        return f.read()

def resume_to_text(resume: Resume) -> str:
    from app.api.match_logic.section_scorer import _section_text, _SECTIONS
    return "\n".join(_section_text(resume, s) for s in _SECTIONS)

# --- Various JD Types Testing ---

def test_score_against_technical_jd(sample_resume):
    jd_text = load_jd("technical.md")
    resume_json = sample_resume.model_dump()
    resume_text = resume_to_text(sample_resume)
    
    # Using dummy embeddings
    res = score_resume_against_jd(
        resume_text=resume_text,
        resume_json=resume_json,
        jd_text=jd_text,
        resume_embedding=[0.1] * 768,
        jd_embedding=[0.2] * 768,
        log_event=False
    )
    
    assert "score" in res
    assert 0 <= res["score"] <= 100
    assert res["breakdown"]["bm25"] > 0

def test_score_against_management_jd(sample_resume):
    jd_text = load_jd("management.md")
    resume_json = sample_resume.model_dump()
    resume_text = resume_to_text(sample_resume)
    
    res = score_resume_against_jd(
        resume_text=resume_text,
        resume_json=resume_json,
        jd_text=jd_text,
        log_event=False
    )
    
    assert "score" in res
    # Management JD might have lower match for a SE resume
    assert res["breakdown"]["seniority"] < 100 

def test_score_against_brief_jd(sample_resume):
    jd_text = load_jd("brief.md")
    resume_json = sample_resume.model_dump()
    resume_text = resume_to_text(sample_resume)
    
    res = score_resume_against_jd(
        resume_text=resume_text,
        resume_json=resume_json,
        jd_text=jd_text,
        log_event=False
    )
    
    assert "score" in res
    assert res["ngram_active"] is False # brief.md has no ngram phrases

# --- Edge Cases ---

def test_edge_empty_jd(sample_resume):
    res = score_resume_against_jd(
        resume_text=resume_to_text(sample_resume),
        resume_json=sample_resume.model_dump(),
        jd_text="",
        log_event=False
    )
    # Current baseline: 0.15 (skill) + 0.05 (edu) + 0.1 (seniority) = 0.30
    assert res["score"] == 30

def test_edge_empty_resume(sample_resume):
    res = score_resume_against_jd(
        resume_text="",
        resume_json={},
        jd_text=load_jd("technical.md"),
        log_event=False
    )
    # Should handle empty resume without crashing
    assert res["score"] >= 0

def test_edge_mismatch_embedding_dims(sample_resume):
    # Length mismatch is handled by _cosine_similarity returning 0.0
    inputs = ScoreInputs(
        resume_text="rt",
        resume_json={},
        jd_text="jd",
        resume_embedding=[0.1, 0.2],
        jd_embedding=[0.1, 0.2, 0.3]
    )
    signals = await compute_signals(inputs)
    assert signals.whole_doc_cos == 0.0

def test_edge_zero_vector(sample_resume):
    inputs = ScoreInputs(
        resume_text="rt",
        resume_json={},
        jd_text="jd",
        resume_embedding=[0.0, 0.0],
        jd_embedding=[0.1, 0.2]
    )
    signals = await compute_signals(inputs)
    assert signals.whole_doc_cos == 0.0

def test_edge_malformed_resume_json():
    # _edu_signal and _seniority_signal try to validate JSON
    # If it's a list instead of dict, model_validate will definitely fail
    res = score_resume_against_jd(
        resume_text="rt",
        resume_json=["this should be a dict"],
        jd_text="Requires PhD degree.",
        log_event=False
    )
    assert res["score"] >= 0
    # New fallback is 0.5 (50%)
    assert res["breakdown"]["education"] == 50

# --- Graduated Penalty Testing ---

def test_graduated_edu_penalty(sample_resume):
    # Resume has Bachelor's (Level 2). 
    # Master's (Level 3) -> 1 level gap -> 1.0 - 0.15 = 0.85
    res = score_resume_against_jd(
        resume_text=resume_to_text(sample_resume),
        resume_json=sample_resume.model_dump(),
        jd_text="Requirements: Master's degree in CS.",
        log_event=False
    )
    assert res["breakdown"]["education"] == 85
    
    # PhD (Level 4) -> 2 level gap -> 1.0 - 0.30 = 0.70
    res = score_resume_against_jd(
        resume_text=resume_to_text(sample_resume),
        resume_json=sample_resume.model_dump(),
        jd_text="Requirements: PhD degree required.",
        log_event=False
    )
    assert res["breakdown"]["education"] == 70

def test_graduated_seniority_penalty(sample_resume):
    # Sample resume has ~4.9 years exp (2021-2026)
    # JD requires 10 years -> 4.9/10 = 0.49. 
    # Quadratic penalty (< 0.5) -> 0.49*0.49*2 = 0.48 -> 48%
    res = score_resume_against_jd(
        resume_text=resume_to_text(sample_resume),
        resume_json=sample_resume.model_dump(),
        jd_text="Requirements: 10+ years of experience.",
        log_event=False
    )
    assert res["breakdown"]["seniority"] == 48

    # JD requires 5 years -> 4.9/5 = 0.98. Linear penalty (>= 0.5) -> 98%
    res = score_resume_against_jd(
        resume_text=resume_to_text(sample_resume),
        resume_json=sample_resume.model_dump(),
        jd_text="Requirements: 5+ years of experience.",
        log_event=False
    )
    assert res["breakdown"]["seniority"] == 98
