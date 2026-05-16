"""
Match logic package: hybrid scoring with BM25, semantic similarity, and hard requirement ceiling.

Exports:
- score_resume_against_jd: Main hybrid scoring function
- detect_ceiling: Hard requirement ceiling detection
- compute_section_scores: Per-section match breakdown
"""

from .hybrid_scorer import score_resume_against_jd
from .ceiling_detector import detect_ceiling, parse_jd_hard_requirements
from .section_scorer import compute_section_scores
from .gap_analyzer import compute_gap_analysis

__all__ = [
    "score_resume_against_jd",
    "detect_ceiling",
    "parse_jd_hard_requirements",
    "compute_section_scores",
    "compute_gap_analysis",
]
