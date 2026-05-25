"""
Runs section-specific tailoring LLM calls for Summary / Experience / Projects / Education.
Skills is deliberately excluded — it is regenerated wholesale post-tailoring via
/api/tailor/generate-skills (see PROMPT_GENERATE_SKILLS_GOLDMINE_SYSTEM).
"""
import logging
import asyncio
from app.models.resume_schema import Resume
from app.core.llm_helpers import (
    tailor_summary,
    tailor_experience,
    tailor_projects,
    tailor_education,
)

logger = logging.getLogger(__name__)
from app.core.renderer import resume_to_plaintext
from app.core.keyword_utils import _STOPWORDS, _ALIASES, _significant_tokens, _top_jd_tokens, _drop_fragments


# Canonical token → display-name lookup (inverts the alias map).
# We prefer the more recognisable form when showing a skill to the user.
_DISPLAY_OVERRIDES: dict[str, str] = {
    "javascript":      "JavaScript",
    "typescript":      "TypeScript",
    "python":          "Python",
    "react":           "React",
    "nextjs":          "Next.js",
    "nodejs":          "Node.js",
    "fastapi":         "FastAPI",
    "django":          "Django",
    "flask":           "Flask",
    "postgresql":      "PostgreSQL",
    "mongodb":         "MongoDB",
    "elasticsearch":   "Elasticsearch",
    "kafka":           "Kafka",
    "kubernetes":      "Kubernetes",
    "docker":          "Docker",
    "terraform":       "Terraform",
    "aws":             "AWS",
    "gcp":             "GCP",
    "azure":           "Azure",
    "machinelearning": "Machine Learning",
    "deeplearning":    "Deep Learning",
    "nlp":             "NLP",
    "computervision":  "Computer Vision",
    "fullstack":       "Full Stack",
    "frontend":        "Frontend",
    "backend":         "Backend",
    "cicd":            "CI/CD",
    "restapi":         "REST API",
    "graphql":         "GraphQL",
    "rag":             "RAG",
    "llm":             "LLM",
    "mlflow":          "MLflow",
    "langchain":       "LangChain",
    "llamaindex":      "LlamaIndex",
    "huggingface":     "Hugging Face",
    "genai":           "Generative AI",
    "webapi":          "Web API",
    "oop":             "OOP",
    "devops":          "DevOps",
    "dataengineering": "Data Engineering",
    "datascience":     "Data Science",
    "mysql":           "MySQL",
    "redis":           "Redis",
    "spark":           "Apache Spark",
    "airflow":         "Apache Airflow",
    "dbt":             "dbt",
    "pytorch":         "PyTorch",
    "tensorflow":      "TensorFlow",
}


def _to_display(canonical: str, jd_text: str) -> str:
    """Convert a canonical token to a user-facing skill name.

    Prefers the override table, then tries to find the original capitalised form
    in the JD (useful for tech names not in the override table).
    Falls back to title-case of the canonical token."""
    if canonical in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[canonical]
    # Scan JD for any token that normalises to this canonical — use its casing.
    import re as _re
    for word in _re.findall(r'[A-Za-z][A-Za-z0-9+#.\-]{1,}', jd_text):
        if word.lower() in _ALIASES and _ALIASES[word.lower()] == canonical:
            return word
        if word.lower() == canonical:
            return word
    return canonical.replace("_", " ").title()


def _derive_skill_additions(
    resume: "Resume",
    tailored_text: str,
    jd_text: str,
    id_start: int = 5000,
) -> list[dict]:
    """Deterministic skill-ADD suggestions grounded in the tailored resume text.

    Only suggests skills that:
      1. Are in the top-50 JD tokens (JD actually wants them).
      2. Appear in the tailored resume text (candidate genuinely has evidence).
      3. Are NOT already in the resume skills section.
      4. Map cleanly to an existing category via skill_taxonomy (no new subsections).

    No LLM involved — zero hallucination risk.
    """
    from app.core import skill_taxonomy as _tax

    jd_top = _top_jd_tokens(jd_text, k=50)
    resume_tokens = _significant_tokens(tailored_text)

    # Skills already in the resume (flat, canonical).
    existing_cats = [s.category for s in (resume.skills or []) if s.category]
    existing_skills_canon = {
        (_ALIASES.get(sk.strip().lower(), sk.strip().lower()))
        for cat in (resume.skills or [])
        for sk in (cat.skills or [])
        if sk and sk.strip()
    }

    candidates = jd_top & resume_tokens - existing_skills_canon
    candidates = _drop_fragments(sorted(candidates))

    suggestions = []
    seen_display = {sk.strip().lower() for cat in (resume.skills or []) for sk in (cat.skills or []) if sk}

    for token in candidates:
        display = _to_display(token, jd_text)
        if display.strip().lower() in seen_display:
            continue
        best_cat = _tax.best_existing_category(token, existing_cats)
        if not best_cat:
            continue
        suggestions.append({
            "id": id_start + len(suggestions),
            "section": "Skills",
            "mode": "add_skill",
            "category": best_cat,
            "skill": display,
            "is_new_category": False,
            "reasoning": f"Found in your tailored resume and required by the Job Description.",
        })

    return suggestions


def build_skills_contexts(resume: Resume) -> tuple[str, str, str]:
    """Build (experience_ctx, projects_ctx, certifications_ctx) blobs for the
    Skills LLM prompt. Each is plain text, caller-truncated downstream."""
    exp_lines = []
    for e in resume.experience[:3]:
        title = (e.title or "").strip()
        company = (e.company or "").strip()
        head = f"{title} @ {company}".strip(" @")
        bullets = [b for b in (e.bullets or []) if b][:2]
        exp_lines.append(head)
        for b in bullets:
            exp_lines.append(f"- {b}")
    experience_ctx = "\n".join(exp_lines)

    proj_lines = []
    for p in resume.projects[:6]:
        name = (p.name or "").strip()
        tech = (p.tech or "").strip()
        head = name + (f" — {tech}" if tech else "")
        proj_lines.append(head)
        for b in (p.bullets or [])[:1]:
            proj_lines.append(f"- {b}")
    projects_ctx = "\n".join(proj_lines)

    certifications_ctx = ", ".join([c for c in (resume.certifications or []) if c])
    return experience_ctx, projects_ctx, certifications_ctx


async def generate_section_suggestions(resume: Resume, jd_text: str) -> dict:
    # Compute missing keywords BEFORE fanning out to tailors so they can
    # inject the top-priority ones into their prompts. Shared with the match
    # scorer (same _significant_tokens) so every honest injection moves the score.
    jd_tokens = _significant_tokens(jd_text)
    resume_tokens = _significant_tokens(resume_to_plaintext(resume))
    missing = jd_tokens - resume_tokens

    top_jd = _top_jd_tokens(jd_text, k=50)
    top_missing = _drop_fragments(sorted(top_jd & missing))[:20]

    # Skills is intentionally NOT generated here. It is a post-tailoring step
    # the user triggers via /api/tailor/generate-skills once the other section
    # edits are accepted — see PROMPT_GENERATE_SKILLS_GOLDMINE_SYSTEM.

    # Parallelize LLM calls
    tasks = [
        tailor_experience([e.model_dump() for e in resume.experience], jd_text, keywords_to_inject=top_missing),
        tailor_projects([p.model_dump() for p in resume.projects], jd_text, keywords_to_inject=top_missing),
        tailor_summary(resume.summary, jd_text, keywords_to_inject=top_missing),
        tailor_education([e.model_dump() for e in resume.education], jd_text, keywords_to_inject=top_missing)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    exp_r = results[0] if not isinstance(results[0], Exception) else []
    proj_r = results[1] if not isinstance(results[1], Exception) else []
    summary_r = results[2] if not isinstance(results[2], Exception) else []
    edu_r = results[3] if not isinstance(results[3], Exception) else []

    if any(isinstance(r, Exception) for r in results):
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                labels = ["Experience", "Projects", "Summary", "Education"]
                logger.warning(f"[tailor_orchestrator] {labels[i]} tailor failed: {r}")

    raw = {
        "Summary": summary_r,
        "Experience": exp_r,
        "Projects": proj_r,
        "Education": edu_r,
    }

    sections: dict = {}
    flat: list = []
    id_counter = 1

    for label, result in raw.items():
        if isinstance(result, Exception):
            logger.warning(f"[tailor_orchestrator] '{label}' failed: {result}")
            sections[label] = []
            continue
        for s in result:
            s["id"] = id_counter
            id_counter += 1
        sections[label] = result
        flat.extend(result)

    # Only return sections that produced suggestions
    non_empty_sections = {k: v for k, v in sections.items() if v}

    # Project names indexed by project_index — used by the frontend carousel.
    project_names = [p.name or f"Project {i+1}" for i, p in enumerate(resume.projects)]

    # jd_tokens / resume_tokens / missing were computed above before the gather.
    missing_sorted = _drop_fragments(sorted(missing))

    return {
        "sections": non_empty_sections,
        "suggestions": flat,
        "project_names": project_names,
        "jd_missing_keywords": missing_sorted,
    }
