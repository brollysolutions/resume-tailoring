"""Per-section cosine similarity for hybrid scoring.

Whole-document embeddings dilute signal: resume "Education" drowns out
"Experience"; JD "Benefits" drowns out "Requirements". This module embeds
JD requirements and resume content blocks separately, then takes the
max cosine across pairs — so a strong specific overlap (resume bullet
matches one JD requirement closely) shows up even when the rest of the
documents are noisy.

Returns the max-pair cosine. Caller blends with whole-doc cosine in
hybrid_scorer.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

# Heuristic markers for the JD "requirements" / "responsibilities" section.
# Anything after one of these headers (until the next header or EOF) is
# treated as the meaningful JD content for embedding.
_JD_REQ_HEADERS = re.compile(
    r"(?im)^\s*(requirements|responsibilities|qualifications|what\s+you[''']ll\s+do|"
    r"who\s+you\s+are|must\s+have|key\s+skills|technical\s+skills|"
    r"role\s+overview|the\s+role|about\s+the\s+role|what\s+we['']re\s+looking\s+for)"
    r"\s*[:\-]?\s*$"
)
_JD_END_HEADERS = re.compile(
    r"(?im)^\s*(benefits|perks|compensation|salary|equal\s+opportunity|"
    r"about\s+(us|the\s+company)|why\s+join|our\s+values?|how\s+to\s+apply|"
    r"location|reports\s+to|employment\s+type)"
    r"\s*[:\-]?\s*$"
)


def extract_jd_requirements(jd_text: str) -> str:
    """Slice the JD down to its requirements/responsibilities portion.

    Falls back to the full JD if no recognizable header is found — a small
    JD with no headers is its own requirements section.
    """
    lines = jd_text.splitlines()
    start: Optional[int] = None
    end: Optional[int] = None
    for i, line in enumerate(lines):
        if start is None and _JD_REQ_HEADERS.match(line):
            start = i + 1
        elif start is not None and _JD_END_HEADERS.match(line):
            end = i
            break
    if start is None:
        return jd_text
    body = "\n".join(lines[start:end if end is not None else len(lines)]).strip()
    return body or jd_text


def resume_content_blocks(resume_json: dict) -> list[str]:
    """Return the resume's substantive content as discrete blocks for
    per-block embedding. Skips contact/education boilerplate that drowns
    out tech signal."""
    blocks: list[str] = []

    if resume_json.get("summary"):
        blocks.append(resume_json["summary"])

    for exp in resume_json.get("experience", []) or []:
        bullets = exp.get("bullets") or []
        if not bullets:
            continue
        header = " ".join(filter(None, [exp.get("title", ""), exp.get("company", "")])).strip()
        blocks.append((header + "\n" + "\n".join(bullets)).strip())

    for proj in resume_json.get("projects", []) or []:
        bullets = proj.get("bullets") or []
        if not bullets and not proj.get("tech"):
            continue
        header = " ".join(filter(None, [proj.get("name", ""), proj.get("tech") or ""])).strip()
        blocks.append((header + "\n" + "\n".join(bullets)).strip())

    skill_text = " ".join(
        s for sk in (resume_json.get("skills") or []) for s in (sk.get("skills") or [])
    ).strip()
    if skill_text:
        blocks.append(skill_text)

    return [b for b in blocks if b]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    ma = sum(x * x for x in a) ** 0.5
    mb = sum(y * y for y in b) ** 0.5
    if ma <= 0 or mb <= 0:
        return 0.0
    return dot / (ma * mb)


async def compute_section_cosine(
    resume_json: dict,
    jd_text: str,
    embedder: Callable[[str], Awaitable[list[float]]],
) -> Optional[float]:
    """Embed JD requirements + each resume content block, return the max
    cosine across pairs.

    Returns None when there's nothing to score (empty resume blocks or
    embedder failure). Caller should treat None as "fall back to
    whole-doc cosine".
    """
    jd_requirements = extract_jd_requirements(jd_text)
    blocks = resume_content_blocks(resume_json)
    if not blocks or not jd_requirements.strip():
        return None

    try:
        jd_vec = await embedder(jd_requirements)
    except Exception:
        return None

    best = 0.0
    for block in blocks:
        try:
            block_vec = await embedder(block)
        except Exception:
            continue
        c = _cosine(jd_vec, block_vec)
        if c > best:
            best = c
    return best
