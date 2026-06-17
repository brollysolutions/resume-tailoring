"""
Ceiling detector: hard requirement penalties from JD analysis.

Detects years of experience gaps, required degrees, seniority level mismatches.
Applies penalties to ceiling (max realistic score) so severe mismatches don't hide
behind keyword tailoring alone.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r'(\d{1,2})[/\-](\d{4})')
_YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MON_YEAR_RE = re.compile(r'([a-z]{3,9})\.?\s+((?:19|20)\d{2})', re.IGNORECASE)
_RANGE_SEP_RE = re.compile(r'\s*(?:–|—|-|\bto\b)\s*', re.IGNORECASE)
_SENIORITY_ORDER = ["junior", "mid", "senior", "staff", "principal", "lead"]

# Matches "5+ years", "5-7 years", "minimum 5 years", "at least 5 years of experience"
_YRS_EXP_RE = re.compile(
    r'(?:minimum\s+|at\s+least\s+|over\s+)?(\d+)\+?\s*(?:[-–]\s*\d+\s*)?'
    r'years?\s*(?:of\s*)?(?:experience|exp\b)',
    re.IGNORECASE,
)

# Label form where "Experience" precedes the number: "Experience: 1-3 Years",
# "Experience – 2+ Years", "Experience 5 Years". Captures the lower bound.
_YRS_EXP_LABEL_RE = re.compile(
    r'experience\s*[:\-–—]?\s*(\d+)\s*(?:[-–—]\s*\d+\s*)?\+?\s*years?\b',
    re.IGNORECASE,
)

# Only match degrees when near "degree", "required", or "qualification"
_DEGREE_RE = re.compile(
    r"\b(bachelor(?:'s)?|b\.s\.|b\.a\.|btech|b\.tech"
    r"|master(?:'s)?|m\.s\.|mba|m\.tech"
    r"|ph\.?d\.?|doctorate|associate(?:'s)?)\b",
    re.IGNORECASE,
)
_DEGREE_CONTEXT_RE = re.compile(
    r"(degree|required|qualification|must\s+have|education)\b",
    re.IGNORECASE,
)
_DEGREE_MAP = {
    "bachelor": "bachelor", "bachelor's": "bachelor", "b.s.": "bachelor", "b.a.": "bachelor",
    "btech": "bachelor", "b.tech": "bachelor",
    "master": "master", "master's": "master", "m.s.": "master", "mba": "master", "m.tech": "master",
    "ph.d.": "phd", "phd": "phd", "doctorate": "phd",
    "associate": "associate", "associate's": "associate",
}

_SENIORITY_TITLE_RE = re.compile(
    r'\b(junior|mid[- ]?level|senior|staff|principal|lead)\b',
    re.IGNORECASE,
)


def parse_jd_hard_requirements(jd_text: str) -> dict:
    """Regex-based extraction of hard requirements from JD text. No LLM, instant.

    Returns same shape as extract_jd_hard_requirements():
      {min_years_experience, required_degrees, seniority_level, required_skills_hard}
    """
    sentences = re.split(r'[.!?\n]+', jd_text)
    
    # 1. Years of experience — filter out company history/fluff
    valid_years = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        matches = _YRS_EXP_RE.findall(sentence) + _YRS_EXP_LABEL_RE.findall(sentence)
        if not matches:
            continue

        sentence_lower = sentence.lower()

        # Check if the sentence is about the company/team experience
        is_company_fluff = False
        if re.search(r'(?:we|company|firm|team|our)\s+(?:have|has|bring|possess)\s+(?:over\s+|more\s+than\s+)?(?:\d+)\+?\s*years', sentence_lower):
            is_company_fluff = True

        if not is_company_fluff:
            for y in matches:
                valid_years.append(int(y))
                
    min_years = min(15, max(valid_years)) if valid_years else None

    # 2. Degrees — ignore preferred/desired degrees
    required_degrees = []
    if _DEGREE_CONTEXT_RE.search(jd_text):
        for sentence in sentences:
            sentence_lower = sentence.lower().strip()
            if not sentence_lower:
                continue
                
            for m in _DEGREE_RE.finditer(sentence_lower):
                raw = m.group(1).rstrip(".")
                canonical = _DEGREE_MAP.get(raw)
                if not canonical:
                    continue
                    
                # Check if this sentence indicates it's preferred
                is_preferred = False
                preferred_indicators = [
                    "preferred", "prefer", "a plus", "desired", "optional", 
                    "nice to have", "advantage", "helpful", "not required",
                    "highly valued", "is a plus", "strongly preferred"
                ]
                for ind in preferred_indicators:
                    if ind in sentence_lower:
                        is_preferred = True
                        break
                        
                if not is_preferred and canonical not in required_degrees:
                    required_degrees.append(canonical)

    # 3. Seniority — check job title area (first 200 chars) first, then full text
    seniority = None
    title_area = jd_text[:200].lower()
    for level in reversed(_SENIORITY_ORDER):
        if level in title_area:
            seniority = level
            break
    if not seniority:
        m = _SENIORITY_TITLE_RE.search(jd_text)
        if m:
            raw = m.group(1).lower().replace("-", "").replace(" ", "")
            seniority = "mid" if "mid" in raw else raw if raw in _SENIORITY_ORDER else None

    return {
        "min_years_experience": min_years,
        "required_degrees": required_degrees,
        "seniority_level": seniority,
        "required_skills_hard": [],
    }


def _parse_date_token(s: str) -> tuple[int, int] | None:
    """Parse date string to (year, month).

    Accepts 'MM/YYYY', 'MM-YYYY', bare 'YYYY', or special strings like 'Present'.
    Returns (year, month) or None if unparseable.
    """
    if not s:
        return None
    s = s.strip().lower()
    if s in {"present", "current", "now", ""}:
        return None

    m = _DATE_RE.search(s)
    if m:
        try:
            month = max(1, min(12, int(m.group(1))))
            year = int(m.group(2))
            return (year, month)
        except ValueError:
            pass

    m = _MON_YEAR_RE.search(s)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month:
            return (int(m.group(2)), month)

    m = _YEAR_RE.search(s)
    if m:
        try:
            return (int(m.group(0)), 1)
        except ValueError:
            pass

    return None


def estimate_years_experience(resume) -> Optional[float]:
    """Sum non-overlapping experience spans from resume.

    Returns total years as float, or None if no parseable dates.
    """
    import datetime as _dt

    spans: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for e in resume.experience:
        raw_start = e.start_date or ""
        raw_end = e.end_date or ""

        start = _parse_date_token(raw_start)
        end = _parse_date_token(raw_end)

        # Whole range may have collapsed into start_date ("Jan 2022 - Present",
        # "2022 - 2024") with end_date empty. Split and parse both halves.
        if not raw_end.strip() and _RANGE_SEP_RE.search(raw_start):
            parts = _RANGE_SEP_RE.split(raw_start, maxsplit=1)
            if len(parts) == 2:
                cand_start = _parse_date_token(parts[0])
                cand_end = _parse_date_token(parts[1])
                tail = parts[1].strip().lower()
                if cand_start is not None and (cand_end is not None or tail in {"present", "current", "now"}):
                    start = cand_start
                    end = cand_end

        if end is None:
            today = _dt.date.today()
            end = (today.year, today.month)

        if start is None:
            continue

        if end < start:
            continue

        spans.append((start, end))

    if not spans:
        return None

    spans.sort()
    merged: list[list] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1][1] = e
        else:
            merged.append([s, e])

    total_months = 0
    for s, e in merged:
        total_months += (e[0] - s[0]) * 12 + (e[1] - s[1])

    return round(total_months / 12.0, 1)


def resume_has_degree(resume, required: list[str]) -> bool:
    """Check if resume contains any of the required degree types.

    Args:
        resume: Resume object
        required: List of degree types ('bachelor', 'master', 'phd', 'associate')

    Returns:
        True if resume has one of the required degrees, False otherwise.
    """
    if not required:
        return True

    canon_aliases = {
        "bachelor": ("bachelor", "b.s.", "bs ", "b.a.", "ba ", "btech", "b.tech", "b.e.", "be "),
        "master": ("master", "m.s.", "ms ", "m.a.", "ma ", "mtech", "m.tech", "mba"),
        "phd": ("phd", "ph.d", "doctor"),
        "associate": ("associate", "a.s.", "as "),
    }

    edu_blob = " ".join((e.degree or "") + " " + (e.field or "") for e in resume.education).lower() + " "

    for req in required:
        keys = canon_aliases.get(req, (req,))
        if any(k in edu_blob for k in keys):
            return True

    return False


def infer_seniority(resume) -> Optional[str]:
    """Infer seniority level from most recent job title.

    Returns one of: 'junior', 'mid', 'senior', 'staff', 'principal', 'lead', or None.
    """
    if not resume.experience:
        return None

    title = (resume.experience[0].title or "").lower()
    for level in reversed(_SENIORITY_ORDER):
        if level in title:
            return level

    return None


def detect_ceiling(resume, hard_reqs: dict) -> dict:
    """Compute realistic score ceiling based on hard JD requirements.

    Detects:
    - Years of experience gaps (penalty based on gap size)
    - Missing required degrees
    - Seniority level mismatches

    Args:
        resume: Resume object
        hard_reqs: Dict with keys: min_years_experience, required_degrees, seniority_level

    Returns:
        {
            "score": int [35-100],
            "reasons": list[str],
            "exp_required": int or None,
            "exp_actual": float or None
        }
    """
    score = 100
    reasons: list[str] = []
    exp_required: Optional[int] = None
    exp_actual: Optional[float] = None

    # Years of experience check
    min_yrs = hard_reqs.get("min_years_experience")
    if isinstance(min_yrs, int) and min_yrs > 0:
        actual = estimate_years_experience(resume)
        exp_required = min_yrs
        exp_actual = actual

        if actual is not None and actual + 0.5 < min_yrs:
            gap = min_yrs - actual
            penalty = int(gap * 8)
            if gap >= 2.5:
                penalty += 15
            score -= penalty
            reasons.append(f"needs {min_yrs}+ yrs (resume ~{actual:g})")

    # Degree check
    degrees = hard_reqs.get("required_degrees") or []
    if degrees and not resume_has_degree(resume, degrees):
        score -= 15
        reasons.append(f"requires {'/'.join(degrees)} degree")

    # Seniority check
    req_level = hard_reqs.get("seniority_level")
    if req_level in _SENIORITY_ORDER:
        actual_level = infer_seniority(resume)
        req_idx = _SENIORITY_ORDER.index(req_level)
        actual_idx = _SENIORITY_ORDER.index(actual_level) if actual_level in _SENIORITY_ORDER else -1

        if actual_idx < req_idx:
            gap = req_idx - actual_idx if actual_idx >= 0 else req_idx + 1
            penalty = gap * 12
            score -= penalty
            reasons.append(
                f"targets {req_level} level"
                + (f" (resume reads {actual_level})" if actual_level else "")
            )

    score = max(35, min(100, score))
    return {
        "score": score,
        "reasons": reasons,
        "exp_required": exp_required,
        "exp_actual": exp_actual,
    }
