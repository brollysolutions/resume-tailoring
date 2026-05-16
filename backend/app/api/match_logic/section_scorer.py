"""
Per-section scoring: Match each resume section separately against JD.

Returns breakdown by Summary, Experience, Projects, Skills for granular feedback.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_SECTIONS = ("Summary", "Experience", "Projects", "Skills")


def _section_text(resume, section: str) -> str:
    """Extract plaintext for one resume section.

    Args:
        resume: Resume object
        section: Section name (Summary, Experience, Projects, Skills)

    Returns:
        Plaintext for that section, or empty string if missing.
    """
    section = section.lower()
    lines: list[str] = []

    if section == "summary":
        if resume.summary:
            lines.append(resume.summary)

    elif section == "experience":
        for e in resume.experience:
            head = f"{e.title} @ {e.company}"
            if e.location:
                head += f" ({e.location})"
            lines.append(head)
            lines.extend(e.bullets or [])

    elif section == "projects":
        for p in resume.projects:
            head = p.name + (f" — {p.tech}" if p.tech else "")
            lines.append(head)
            lines.extend(p.bullets or [])

    elif section == "skills":
        for sk in resume.skills:
            lines.append(f"{sk.category}: {', '.join(sk.skills or [])}")

    return "\n".join(filter(None, lines))


async def compute_section_scores(
    resume,
    resume_json: dict,
    jd_text: str,
    jd_embedding: Optional[list[float]] = None,
) -> dict:
    """Score each non-empty resume section against JD independently.

    Returns:
        {
            "Summary": int or None,
            "Experience": int or None,
            "Projects": int or None,
            "Skills": int or None
        }
    """
    from .hybrid_scorer import score_resume_against_jd
    from app.core.vector_db import get_embedding

    texts = {s: _section_text(resume, s) for s in _SECTIONS}
    non_empty = [(s, t) for s, t in texts.items() if t.strip()]

    if not non_empty:
        return {s: None for s in _SECTIONS}

    # Embed JD once; embed each section in parallel
    try:
        embed_tasks = [get_embedding(t) for _, t in non_empty]
        if jd_embedding is None:
            embed_tasks.append(get_embedding(jd_text))
        results_emb = await asyncio.gather(*embed_tasks, return_exceptions=True)

        section_embeddings = {}
        for i, (section, _) in enumerate(non_empty):
            emb = results_emb[i]
            section_embeddings[section] = emb if isinstance(emb, list) else None

        if jd_embedding is None:
            raw_jd = results_emb[-1]
            jd_embedding = raw_jd if isinstance(raw_jd, list) else None
    except Exception as e:
        logger.warning(f"Section embedding failed: {e}")
        section_embeddings = {s: None for s, _ in non_empty}

    out: dict = {s: None for s in _SECTIONS}

    for section, text in non_empty:
        section_json = {}
        if section == "Skills":
            section_json = {"skills": resume_json.get("skills", [])}

        result = score_resume_against_jd(
            text, section_json, jd_text,
            resume_embedding=section_embeddings.get(section),
            jd_embedding=jd_embedding,
        )
        out[section] = result["score"]

    return out
