"""Project synthesis and text humanization."""
import json
import logging
from app.core.llm_client import _chat
from app.core.llm_helpers import llm_clean_tech_field

logger = logging.getLogger(__name__)


async def analyze_jd_for_projects(jd_text: str) -> dict:
    """Stage A: extract metadata from JD for project synthesis."""
    system = """Extract metadata for building realistic portfolio projects.
Return JSON:
{
  "domain": "primary technical domain (4-7 words)",
  "required_skills": ["top 5 hard skills — exact tool/language names"],
  "scale_signal": "startup-MVP | mid-size-product | enterprise",
  "problem_shapes": ["specific problem type 1", "specific problem type 2"],
  "industry": "fintech | healthtech | saas | e-commerce | devtools | media | logistics | other"
}"""
    try:
        content = await _chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"JOB DESCRIPTION:\n{jd_text[:3000]}"}],
            json_mode=True,
        )
        return json.loads(content)
    except Exception as e:
        logger.warning(f"[analyze_jd_for_projects] failed: {e}")
        return {}


async def synthesize_projects(
    jd_analysis: dict,
    candidate_skills: list,
    seed: str,
    exclude_names: list,
    count: int = 3,
    seniority: str = "junior",
    avg_words: int = 20,
    n_bullets: int = 4,
    bullet_style_sample: str = "",
    missing_keywords: list = None,
) -> list:
    """Stage B: generate portfolio projects tailored to JD."""
    skills_str = ", ".join(candidate_skills) if candidate_skills else "Python, JavaScript"
    exclude_block = (
        "\n\nEXCLUDE — do not produce projects similar to these names:\n"
        + "\n".join(f"- {n}" for n in exclude_names[:10])
    ) if exclude_names else ""

    if seniority == "fresher":
        scale_rules = (
            "- ALLOWED: local benchmarks, learning outcomes, free-tier deployments, small accuracy/F1.\n"
            "- BANNED: production traffic (10k+ users, 1k+ RPS), team/customer counts, SLA percentages."
        )
    elif seniority == "junior":
        scale_rules = (
            "- ALLOWED: local benchmarks, modest datasets, modest latency (few hundred RPS), repo stars.\n"
            "- BANNED: enterprise traffic, '1B+ requests', cost-savings, customer counts."
        )
    elif seniority == "mid":
        scale_rules = (
            "- ALLOWED: regional/team-scale (few thousand RPS), datasets in low millions.\n"
            "- BANNED: hyperscale (1M+ users, 100k+ RPS), cost-savings, revenue."
        )
    else:  # senior
        scale_rules = (
            "- ALLOWED: enterprise-scale anchors (tech-grounded: latency, throughput, p99).\n"
            "- BANNED: customer counts, revenue — still personal projects."
        )

    style_block = ""
    if bullet_style_sample.strip():
        style_block = (
            "\n\nSTYLE REFERENCE — match the tone/structure of the candidate's existing bullets:\n"
            + bullet_style_sample
        )

    missing_block = ""
    if missing_keywords:
        missing_block = (
            "\n\nCRITICAL - MISSING JD KEYWORDS:\n"
            "Weave as many as possible into project tech stacks and bullets:\n"
            + ", ".join(missing_keywords)
        )

    bullets_example = ", ".join(f'"technical bullet {i + 1}"' for i in range(n_bullets))

    system = f"""You are a senior engineer writing zero-cost portfolio projects for a job candidate.
Produce {count + 2} realistic personal projects.

CANDIDATE SENIORITY: {seniority}
TARGET BULLET LENGTH: ~{avg_words} words each.

SCALE CALIBRATION:
{scale_rules}
- Never invent metrics. If not credible at this seniority, OMIT the number.

HARD CONSTRAINTS:
1. GROUND EVERY PROJECT IN CANDIDATE SKILLS — build projects the candidate could
   credibly have built with the tools they already know. JD REQUIRED SKILLS and
   MISSING JD KEYWORDS are secondary flavor layered on top; weave them in ONLY where
   they are genuine technologies that fit a coherent project. NEVER build a project
   around a token you do not understand, and NEVER turn an unknown token or acronym
   into a project name or tech entry.
2. NO HALLUCINATED NAMES. Project name MUST be a plain-English, meaningful noun phrase
   describing a real, buildable project. NO undefined or invented acronyms (e.g. "LPA"),
   NO invented product or company names. If a JD token is an unclear acronym, expand it
   to its full term or skip it entirely.
   - GOOD: "Event-Driven Order Pipeline", "Kafka Audit Log Service"
   - BAD: "LPA Generation Pipeline", "Event-Driven System for", "Java Backend", dangling prepositions
3. Each project MUST contain EXACTLY {n_bullets} bullets — never fewer, never more.
4. Each project solves a SPECIFIC named problem.
5. BANNED: $ revenue, $ saved, customer count, cost reduction, business impact.
6. Projects span different DOMAINS: data | product | infra | ml | tools — no duplicates.
7. Bullets describe BUILT and WHY — tech decisions, libraries, tradeoffs, architecture.
8. Banned words: "revolutionized", "spearheaded", "leveraged", "cutting-edge", "robust",
   "scalable", "innovative", "seamless", "state-of-the-art", "saved $", "revenue".
9. Project name: 2–5 words, complete noun phrase, NO geographic modifiers (Bangalore-based,
   US-based, etc.), NO company names, NO region/country/city tokens.
10. DIVERSITY SEED: {seed} — use as creative fingerprint to produce distinct projects.
11. TENSE + TONE: SIMPLE PAST. No contractions, no "just"/"super"/"really". Varied openers.

Return JSON:
{{
  "projects": [
    {{
      "name": "short project name",
      "tech": "Tool1, Tool2, Tool3",
      "bullets": [{bullets_example}],
      "domain_tag": "data | product | infra | ml | tools",
      "interview_brief": "2-3 sentences: problem, approach, result"
    }}
  ]
}}"""

    req_skills = ", ".join(jd_analysis.get("required_skills", [])) or skills_str
    user = (
        f"JD REQUIRED SKILLS:\n{req_skills}\n\n"
        f"CANDIDATE SKILLS:\n{skills_str}\n"
        f"{missing_block}\n\n"
        f"JD ANALYSIS:\n"
        f"Domain: {jd_analysis.get('domain', 'software engineering')}\n"
        f"Scale: {jd_analysis.get('scale_signal', 'mid-size-product')}\n"
        f"Problems: {'; '.join(jd_analysis.get('problem_shapes', []))}\n"
        f"Industry: {jd_analysis.get('industry', 'tech')}"
        f"{exclude_block}{style_block}"
    )

    try:
        content = await _chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            json_mode=True,
        )
        parsed = json.loads(content)
        projects = parsed.get("projects", [])
        for proj in projects:
            if isinstance(proj, dict) and proj.get("tech"):
                proj["tech"] = await llm_clean_tech_field(proj["tech"])
        return projects
    except Exception as e:
        logger.warning(f"[synthesize_projects] json_mode failed, retrying: {e}")
        try:
            content = await _chat(
                [{"role": "system", "content": system + "\nRespond ONLY with valid JSON."},
                 {"role": "user", "content": user}],
                json_mode=False,
            )
            start = content.find("{"); end = content.rfind("}") + 1
            projects = json.loads(content[start:end]).get("projects", []) if start != -1 and end > 0 else []
            for proj in projects:
                if isinstance(proj, dict) and proj.get("tech"):
                    proj["tech"] = await llm_clean_tech_field(proj["tech"])
            return projects
        except Exception:
            return []


_HUMANIZER_RULES = """Rewrite each text so it sounds like a real engineer wrote it.

RULES (all mandatory):
1. Natural, direct, like someone describing their own work.
2. Vary sentence openers — never start two the same way.
   Good: "Shipped", "Cut", "Owned", "Designed", "Migrated", "Reduced", "Built".
3. Preserve every number, percentage, metric, and tool name EXACTLY.
4. Banned words: "robust", "scalable", "innovative", "seamless", "leveraged",
   "spearheaded", "cutting-edge", "revolutionized", "transformed", "saved $".
5. Active voice only.
6. Max 22 words per item.
7. Same length/structure as input — don't expand or shrink.
8. Return ONLY valid JSON — same keys, only "t" values changed."""


async def humanize_texts(texts: list[str]) -> list[str]:
    """Batch humanize text snippets. Order preserved."""
    if not texts:
        return texts

    flat = [{"i": i, "t": t} for i, t in enumerate(texts)]

    try:
        content = await _chat(
            [{"role": "system", "content": _HUMANIZER_RULES},
             {"role": "user", "content": f"Humanize:\n{json.dumps(flat)}\n\nReturn: {{\"items\": [{{\"i\": <int>, \"t\": \"<humanized>\"}}]}}"}],
            json_mode=True,
        )
        parsed = json.loads(content)
        lookup = {item["i"]: item["t"] for item in parsed.get("items", [])}
        return [lookup.get(i, t) for i, t in enumerate(texts)]
    except Exception as e:
        logger.warning(f"[humanize_texts] failed, using originals: {e}")
        return texts


async def humanize_project_bullets(projects: list, avg_words: int = 20, seniority: str = "junior") -> list:
    """Post-process generated project bullets to sound human."""
    if not projects:
        return projects

    flat = []
    for pi, proj in enumerate(projects):
        for bi, bullet in enumerate(proj.get("bullets", [])):
            flat.append({"pi": pi, "bi": bi, "t": bullet})

    system = f"""You are a senior engineer rewriting resume bullets to sound natural.

CANDIDATE SENIORITY: {seniority}

RULES (all mandatory):
1. PROFESSIONAL register. Read like experienced engineer's resume, not chat.
2. TENSE: SIMPLE PAST. "builds" → "built", "is using" → "used", "just started" → "wrote".
3. TONE: NO contractions ("it's" → "it is"), NO filler ("super", "really", "just"),
   NO asides ("which is super helpful").
4. Vary sentence openers — never start two bullets same way.
   Good: "Built", "Designed", "Migrated", "Reduced", "Owned", "Integrated", "Shipped".
5. PRESERVE every metric, number, percentage, tool EXACTLY. Do NOT invent metrics.
6. Banned words: "robust", "scalable", "innovative", "seamless", "leveraged",
   "spearheaded", "cutting-edge", "revolutionized", "transformed", "super", "really".
7. Active voice only — no "was built", "were reduced".
8. Aim ~{avg_words} words per bullet (match candidate's bullets).
9. Return ONLY valid JSON — same keys, only "t" values changed."""

    try:
        content = await _chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"Humanize:\n{json.dumps(flat)}\n\nReturn: {{\"bullets\": [{{\"pi\": <int>, \"bi\": <int>, \"t\": \"<humanized>\"}}]}}"}],
            json_mode=True,
        )
        parsed = json.loads(content)
        lookup = {(b["pi"], b["bi"]): b["t"] for b in parsed.get("bullets", [])}

        result = []
        for pi, proj in enumerate(projects):
            new_bullets = [
                lookup.get((pi, bi), bullet)
                for bi, bullet in enumerate(proj.get("bullets", []))
            ]
            result.append({**proj, "bullets": new_bullets})
        return result
    except Exception as e:
        logger.warning(f"[humanize_project_bullets] failed, using originals: {e}")
        return projects
