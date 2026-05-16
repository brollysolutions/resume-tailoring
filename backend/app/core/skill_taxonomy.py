"""Deterministic skill→domain map used to keep the LLM honest about which
category a proposed skill belongs in. This is the safety net for
`tailor_skills`: after the LLM returns placements, we sanity-check each one
against this taxonomy and reroute (or drop) suggestions that put a skill in
an obviously wrong category (e.g. TypeScript under "Generative AI & NLP").

Returning `None` from any helper means "the taxonomy can't decide" — let the
LLM's choice through unchanged. We only override when we are confident.
"""

# Tech-domain coordinate for a skill. Domains are deliberately fine-grained
# so a category hint set can intersect with the right ones.
SKILL_DOMAIN: dict[str, str] = {
    # Web / Frontend
    "typescript": "web/frontend",
    "javascript": "web/frontend",
    "react": "web/frontend",
    "nextjs": "web/frontend",
    "vue": "web/frontend",
    "angular": "web/frontend",
    "svelte": "web/frontend",
    "html": "web/frontend",
    "css": "web/frontend",
    "tailwind": "web/frontend",
    "tailwindcss": "web/frontend",
    "sass": "web/frontend",
    "redux": "web/frontend",
    # Languages — backend / general purpose
    "python": "backend/python",
    "java": "backend/jvm",
    "kotlin": "backend/jvm",
    "scala": "backend/jvm",
    "go": "backend/general",
    "golang": "backend/general",
    "rust": "backend/systems",
    "c++": "systems",
    "cpp": "systems",
    "c": "systems",
    "c#": "backend/dotnet",
    "csharp": "backend/dotnet",
    # .NET ecosystem
    ".net": "backend/dotnet",
    "dotnet": "backend/dotnet",
    "asp.net": "backend/dotnet",
    "aspnet": "backend/dotnet",
    "aspnetcore": "backend/dotnet",
    # Python web/back-end
    "django": "backend/python",
    "flask": "backend/python",
    "fastapi": "backend/python",
    # JVM frameworks
    "spring": "backend/jvm",
    "springboot": "backend/jvm",
    # Node back-end
    "express": "backend/node",
    "nodejs": "backend/node",
    "nestjs": "backend/node",
    # Databases
    "postgresql": "database/sql",
    "postgres": "database/sql",
    "mysql": "database/sql",
    "sqlserver": "database/sql",
    "mssql": "database/sql",
    "sqlite": "database/sql",
    "mongodb": "database/nosql",
    "dynamodb": "database/nosql",
    "cassandra": "database/nosql",
    "redis": "database/cache",
    "elasticsearch": "database/search",
    "opensearch": "database/search",
    # Data engineering / streaming / batch
    "kafka": "data/streaming",
    "kinesis": "data/streaming",
    "spark": "data/batch",
    "hadoop": "data/batch",
    "airflow": "data/orchestration",
    "dbt": "data/transform",
    "snowflake": "data/warehouse",
    "bigquery": "data/warehouse",
    "redshift": "data/warehouse",
    # ML / DL / NLP / GenAI
    "pytorch": "ml/dl",
    "tensorflow": "ml/dl",
    "scikit-learn": "ml/classical",
    "sklearn": "ml/classical",
    "pandas": "ml/dataframes",
    "numpy": "ml/dataframes",
    "huggingface": "ml/nlp",
    "spacy": "ml/nlp",
    "nltk": "ml/nlp",
    "langchain": "ml/genai",
    "llamaindex": "ml/genai",
    "rag": "ml/genai",
    "llm": "ml/genai",
    "openai": "ml/genai",
    "mlflow": "ml/ops",
    # Infra / DevOps
    "docker": "infra/container",
    "kubernetes": "infra/container",
    "terraform": "infra/iac",
    "ansible": "infra/iac",
    "aws": "infra/cloud",
    "gcp": "infra/cloud",
    "azure": "infra/cloud",
    "linux": "infra/os",
    # Tooling
    "git": "tooling/vcs",
    "github": "tooling/vcs",
    "gitlab": "tooling/vcs",
    "bitbucket": "tooling/vcs",
    "jira": "tooling/pm",
    "postman": "tooling/api",
    "pytest": "tooling/test",
    "junit": "tooling/test",
}


# Category-name (lowercased) → set of domains that fit cleanly. The match in
# `category_accepts` is by exact category lowercase; partial / fuzzy matches
# happen via `_existing_covering_category` for the NEW-subsection guard.
CATEGORY_HINT: dict[str, set[str]] = {
    # AI / ML clusters
    "generative ai & nlp": {"ml/genai", "ml/nlp"},
    "generative ai": {"ml/genai"},
    "ai/ml algorithms": {"ml/dl", "ml/classical", "ml/dataframes"},
    "ai & ml": {"ml/dl", "ml/classical", "ml/dataframes", "ml/genai", "ml/nlp"},
    "machine learning": {"ml/dl", "ml/classical", "ml/dataframes"},
    # Cloud / DevOps
    "cloud technologies": {"infra/cloud", "infra/iac", "infra/container"},
    "cloud & devops": {"infra/cloud", "infra/iac", "infra/container", "tooling/vcs"},
    "devops & mlops": {"infra/cloud", "infra/iac", "infra/container", "ml/ops"},
    "devops": {"infra/cloud", "infra/iac", "infra/container"},
    "mlops": {"ml/ops", "infra/container", "infra/cloud"},
    # Languages / fundamentals
    "core fundamentals": {"systems", "backend/general", "backend/jvm", "backend/dotnet"},
    "languages": {"web/frontend", "backend/general", "backend/jvm",
                  "backend/dotnet", "backend/python", "systems"},
    "programming languages": {"web/frontend", "backend/general", "backend/jvm",
                              "backend/dotnet", "backend/python", "systems"},
    # Full-stack / backend / frontend
    "full stack development": {"web/frontend", "backend/python", "backend/node",
                               "backend/dotnet", "backend/jvm", "backend/general",
                               "backend/systems", "database/sql", "database/nosql",
                               "tooling/api", "tooling/test", "tooling/vcs"},
    "fullstack": {"web/frontend", "backend/python", "backend/node",
                  "backend/dotnet", "backend/jvm", "backend/general",
                  "backend/systems", "database/sql", "database/nosql"},
    "application development": {"web/frontend", "backend/python", "backend/node",
                                 "backend/dotnet", "backend/jvm", "backend/general",
                                 "backend/systems", "database/sql"},
    "backend": {"backend/python", "backend/node", "backend/dotnet",
                "backend/jvm", "backend/general", "backend/systems",
                "database/sql", "database/nosql", "tooling/api"},
    "backend & engineering": {"backend/python", "backend/node", "backend/dotnet",
                              "backend/jvm", "backend/general", "backend/systems"},
    "frontend": {"web/frontend"},
    "web development": {"web/frontend", "backend/python", "backend/node",
                        "backend/dotnet", "backend/jvm"},
    # Data
    "databases": {"database/sql", "database/nosql", "database/cache",
                  "database/search", "data/warehouse"},
    "data engineering": {"data/streaming", "data/batch", "data/orchestration",
                         "data/transform", "data/warehouse", "database/sql"},
    # Tools / testing
    "tools": {"tooling/vcs", "tooling/pm", "tooling/api", "tooling/test"},
    "testing": {"tooling/test"},
}


def normalize_skill(s: str) -> str:
    """Lowercase, strip, collapse spaces — used as a dict key for SKILL_DOMAIN."""
    return s.strip().lower().replace(" ", "")


def normalize_category(s: str) -> str:
    """Lowercase + strip — used as a dict key for CATEGORY_HINT."""
    return s.strip().lower()


def domain_of(skill: str) -> str | None:
    """Look up a skill's domain coordinate. Returns None when unknown."""
    return SKILL_DOMAIN.get(normalize_skill(skill))


def category_accepts(category: str, skill: str) -> bool | None:
    """True/False if both sides are known; None when we can't decide.
    Callers should treat None as 'leave the LLM's decision alone'."""
    dom = domain_of(skill)
    if dom is None:
        return None
    hints = CATEGORY_HINT.get(normalize_category(category))
    if hints is None:
        return None
    return dom in hints


def best_existing_category(skill: str, existing_cats: list[str]) -> str | None:
    """Find the single best-fit existing category for a skill.

    Returns the category name when exactly one existing category covers the
    skill's domain. Returns None when zero or many match (caller drops or
    keeps unchanged)."""
    dom = domain_of(skill)
    if dom is None:
        return None
    matches = [c for c in existing_cats if dom in CATEGORY_HINT.get(normalize_category(c), set())]
    if len(matches) == 1:
        return matches[0]
    return None


def existing_covering_category(new_name: str, existing_cats: list[str]) -> str | None:
    """If a proposed NEW: <name> overlaps in domain hints with an existing
    category, return that existing category — caller should reroute companions
    there instead of creating a duplicate subsection."""
    new_hints = CATEGORY_HINT.get(normalize_category(new_name))
    if not new_hints:
        return None
    for c in existing_cats:
        if CATEGORY_HINT.get(normalize_category(c), set()) & new_hints:
            return c
    return None
