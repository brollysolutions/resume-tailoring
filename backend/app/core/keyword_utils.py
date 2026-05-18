"""Shared tokenization + JD keyword helpers.

Both the match scorer (`app.api.match`) and the tailoring orchestrator
(`app.core.tailor_orchestrator`) need to agree on what counts as a JD keyword.
If the LLM injects a token from a different set than the scorer counts,
injection effort doesn't move the score.

Normalization pipeline: lowercase regex tokens -> alias map -> spaCy lemma.
This collapses "apis"->"api", "react.js"->"react", "k8s"->"kubernetes",
"deploying"->"deploy", so injected keywords and JD tokens line up.
"""
import logging
import re
from collections import Counter
from functools import lru_cache

logger = logging.getLogger(__name__)


_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "had", "her", "was", "one", "our", "out", "day", "get", "has", "him",
    "his", "how", "man", "new", "now", "old", "see", "two", "way", "who",
    "boy", "did", "its", "let", "put", "say", "she", "too", "use", "this",
    "that", "with", "have", "from", "they", "will", "what", "your", "when",
    "make", "like", "into", "time", "look", "more", "want", "work", "good",
    "such", "than", "then", "them", "well", "were", "been", "would", "there",
    "their", "about", "could", "other", "these", "which", "while", "where",
    "after", "before", "between", "during", "through", "above", "below",
    "under", "over", "very", "much", "many", "some", "also", "only", "just",
    "must", "should", "might", "shall", "onto", "upon", "across",
    "within", "without", "against", "toward", "towards", "year", "years",
    "month", "months", "week", "weeks", "today", "yesterday", "tomorrow",
    "high", "low", "best", "great", "small", "large", "big", "long", "short",
    "able", "etc", "via", "per", "yet", "still", "even", "ever", "never",
    "always", "often", "sometimes", "usually", "really", "actually",
    "including", "include", "includes",
    "i", "me", "my", "we", "us", "ourselves", "myself", "ours",
    "ability", "abilities", "skill", "skills", "knowledge", "experience",
    "experiences", "team", "teams", "company", "companies", "role", "roles",
    "job", "jobs", "position", "positions", "candidate", "candidates",
    "responsibility", "responsibilities", "requirement", "requirements",
    "qualification", "qualifications", "preferred", "required",
    "looking", "seeking", "needed", "need", "needs", "ideal", "perfect",
    "join", "growing", "passionate", "strong", "solid", "excellent",
    # Fragments of compound tech terms — when these slip past the pre-normalize
    # pass they leak as standalone "skills". Reject them as standalone tokens;
    # the compound form is captured via _COMPOUND_REWRITES.
    "full", "stack", "end", "side", "part", "top", "core", "basic",
    "advanced", "front", "back", "level", "based",
    # Generic tech verbs & nouns — too common to indicate gaps
    "code", "develop", "develop", "implementation", "implement", "create",
    "build", "provide", "support", "maintain", "ensure", "fine",
    "application", "system", "software", "service", "solution", "process",
    "feature", "manage", "test", "verify",
})


# Curated JD-noise vocabulary — kept separate from _STOPWORDS so it's obvious
# what is "English stopword" vs "structural JD garbage". Anything here is
# dropped post-normalization in both _significant_tokens and _top_jd_tokens.
_BLOCKED_GENERIC = frozenset({
    # generic job titles (rank high by frequency but say nothing about skills)
    "engineer", "engineers", "developer", "developers", "manager", "managers",
    "analyst", "analysts", "architect", "architects", "specialist",
    "specialists", "consultant", "consultants", "associate", "associates",
    "lead", "leader", "senior", "junior", "principal", "staff", "intern",
    "interns", "fresher", "freshers", "expert", "experts", "professional",
    "professionals", "engineering", "developing",
    # structural / metadata fields that repeat in JD headers
    "description", "descriptions", "location", "locations", "address",
    "addresses", "city", "country", "state", "region", "remote", "hybrid",
    "onsite", "salary", "salaries", "benefit", "benefits", "package",
    "packages", "compensation", "ctc", "duty", "duties", "responsibility",
    "responsibilities", "summary", "overview", "about",
    # vague qualifiers — every JD says these
    "framework", "frameworks", "tool", "tools", "technology", "technologies",
    "platform", "platforms", "environment", "environments", "domain",
    "domains", "industry", "industries", "stakeholder", "stakeholders",
    "communication", "collaboration", "collaborative",
    "proficiency", "proficient", "expertise", "familiarity", "familiar",
    "understanding", "competency", "competence",
    # employment fluff
    "employee", "employees", "employer", "employment", "career", "careers",
    "opportunity", "opportunities", "applicant", "applicants",
})


# Multi-word compound tech terms — collapsed to a single canonical token BEFORE
# tokenization so "Full Stack" becomes "fullstack" instead of two fragments.
# Keys must be lowercase; matching is whitespace-insensitive (re.sub handles
# multiple spaces).
_COMPOUND_REWRITES: dict[str, str] = {
    "full stack": "fullstack",
    "full-stack": "fullstack",
    "machine learning": "machinelearning",
    "deep learning": "deeplearning",
    "computer vision": "computervision",
    "natural language processing": "nlp",
    "data science": "datascience",
    "data engineering": "dataengineering",
    "data analytics": "dataanalytics",
    "data analyst": "dataanalyst",
    "data analysis": "dataanalysis",
    "web api": "webapi",
    "rest api": "restapi",
    "restful api": "restapi",
    "graph ql": "graphql",
    "ci cd": "cicd",
    "ci/cd": "cicd",
    "front end": "frontend",
    "front-end": "frontend",
    "back end": "backend",
    "back-end": "backend",
    "object oriented": "oop",
    "object-oriented": "oop",
}


def _pre_normalize(text: str) -> str:
    """Collapse known multi-word tech terms BEFORE tokenization."""
    lowered = text.lower()
    for compound, canonical in _COMPOUND_REWRITES.items():
        lowered = lowered.replace(compound, canonical)
    return lowered


# Canonical alias map. Left side -> right side. Both sides should be lowercase
# and already match the tokenizer regex. Order does not matter; transitive
# chains are NOT resolved (keep map flat).
_ALIASES: dict[str, str] = {
    # JavaScript ecosystem
    "js": "javascript",
    "javascript": "javascript",
    "react.js": "react",
    "reactjs": "react",
    "node.js": "nodejs",
    "node": "nodejs",
    "next.js": "nextjs",
    "vue.js": "vue",
    "express.js": "express",
    "ts": "typescript",
    # Python ecosystem
    "py": "python",
    "py3": "python",
    "python3": "python",
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    # Cloud / DevOps
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "kubernetes": "kubernetes",
    "tf": "terraform",
    "iac": "terraform",
    "ci/cd": "cicd",
    "ci-cd": "cicd",
    "cicd": "cicd",
    "aws": "aws",
    "gcp": "gcp",
    "azure": "azure",
    "ec2": "aws",
    "s3": "aws",
    "lambda": "aws",
    # Databases
    "postgres": "postgresql",
    "psql": "postgresql",
    "postgresql": "postgresql",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "redis": "redis",
    "mysql": "mysql",
    "elasticsearch": "elasticsearch",
    "es": "elasticsearch",
    # ML / AI
    "ml": "machinelearning",
    "machine-learning": "machinelearning",
    "ai": "ai",
    "nlp": "nlp",
    "cv": "computervision",
    "computer-vision": "computervision",
    "llm": "llm",
    "llms": "llm",
    "gen-ai": "genai",
    "genai": "genai",
    "rag": "rag",
    # Misc
    "rest": "restapi",
    "restful": "restapi",
    "apis": "api",
    "api": "api",
    "graphql": "graphql",
    "gql": "graphql",
    "oop": "oop",
    "tdd": "tdd",
    "bdd": "bdd",
    "ux": "ux",
    "ui": "ui",
    "dba": "database",
    "etl": "etl",
    "elt": "etl",
    "qa": "qa",
    "sre": "sre",
    "devops": "devops",
    "fullstack": "fullstack",
    "full-stack": "fullstack",
    "frontend": "frontend",
    "front-end": "frontend",
    "backend": "backend",
    "back-end": "backend",
}


# Lazy spaCy load. Keeps uvicorn cold start fast — model only loads on first
# tokenization call (similar pattern to embedder in vector_db.py).
_nlp = None
_nlp_failed = False
_nlp_ner = None
_nlp_ner_failed = False


def _get_nlp():
    global _nlp, _nlp_failed
    if _nlp is not None or _nlp_failed:
        return _nlp
    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    except Exception as e:
        logger.warning("[keyword_utils] spaCy load failed (%s) — falling back to alias-only normalization", e)
        _nlp_failed = True
        _nlp = None
    return _nlp


def _get_nlp_ner():
    """Separate spaCy pipeline with NER enabled — used to drop GPE/PERSON/ORG
    tokens from JD keyword ranking (cities, company names, etc.)."""
    global _nlp_ner, _nlp_ner_failed
    if _nlp_ner is not None or _nlp_ner_failed:
        return _nlp_ner
    try:
        import spacy
        _nlp_ner = spacy.load("en_core_web_sm", disable=["parser"])
    except Exception as e:
        logger.warning("[keyword_utils] spaCy NER load failed (%s) — entity filter disabled", e)
        _nlp_ner_failed = True
        _nlp_ner = None
    return _nlp_ner


# Entity labels treated as "not a tech keyword". GPE/LOC = geography,
# PERSON/ORG = proper names, DATE/TIME/CARDINAL/MONEY = numerics.
_DROP_ENT_LABELS = frozenset({
    "GPE", "LOC", "PERSON", "ORG", "DATE", "TIME", "CARDINAL", "MONEY", "QUANTITY", "PERCENT",
})


@lru_cache(maxsize=64)
def _jd_entity_tokens(jd_text: str) -> frozenset:
    """Return normalized tokens that spaCy NER classified as locations,
    persons, orgs, dates, or numerics. Cached per JD text (full string key)."""
    nlp = _get_nlp_ner()
    if nlp is None:
        return frozenset()
    try:
        doc = nlp(jd_text[:20000])
    except Exception as e:
        logger.warning("[keyword_utils] NER parse failed: %s", e)
        return frozenset()
    out: set[str] = set()
    for ent in doc.ents:
        if ent.label_ not in _DROP_ENT_LABELS:
            continue
        for tok in re.findall(r'\b[a-z][a-z0-9+#.\-]{2,}\b', ent.text.lower()):
            norm = _normalize_token(tok)
            if norm:
                out.add(norm)
    return frozenset(out)


@lru_cache(maxsize=8192)
def _normalize_token(tok: str) -> str:
    """Lowercase -> alias lookup -> spaCy lemma fallback. Returns canonical form.
    Empty string means the token should be dropped."""
    if not tok:
        return ""
    tok = tok.lower().strip()
    if not tok:
        return ""
    # Alias map first — handles tech-specific variations spaCy doesn't know.
    if tok in _ALIASES:
        return _ALIASES[tok]
    nlp = _get_nlp()
    if nlp is None:
        return tok
    try:
        doc = nlp(tok)
        if doc and doc[0].lemma_:
            lemma = doc[0].lemma_.lower().strip()
            return lemma or tok
    except Exception:
        pass
    return tok


def _tokenize_raw(text: str) -> list[str]:
    """Regex tokenize — keeps tech-friendly punctuation (.+#-).
    Runs _pre_normalize first to collapse multi-word compound tech terms."""
    return re.findall(r'\b[a-z][a-z0-9+#.\-]{2,}\b', _pre_normalize(text))


def _significant_tokens(text: str) -> set:
    """Tokenize text, drop stopwords + curated JD noise, normalize via
    alias + lemma. Returns a set of canonical tokens — used as both the
    injection target (orchestrator) and scoring denominator (match)."""
    out: set[str] = set()
    for raw in _tokenize_raw(text):
        if raw in _STOPWORDS or raw in _BLOCKED_GENERIC:
            continue
        norm = _normalize_token(raw)
        if not norm or norm in _STOPWORDS or norm in _BLOCKED_GENERIC:
            continue
        out.add(norm)
    return out


def _top_jd_tokens(jd_text: str, k: int = 50, min_freq: int = 2) -> set:
    """Return up to k most-frequent significant normalized tokens in the JD.

    Filters: English stopwords, curated JD noise (_BLOCKED_GENERIC), and
    NER entities (cities, persons, orgs, dates, numerics). Tokens appearing
    fewer than min_freq times are dropped to suppress one-off noise."""
    counts: Counter = Counter()
    for raw in _tokenize_raw(jd_text):
        if raw in _STOPWORDS or raw in _BLOCKED_GENERIC:
            continue
        norm = _normalize_token(raw)
        if not norm or norm in _STOPWORDS or norm in _BLOCKED_GENERIC:
            continue
        counts[norm] += 1
    if not counts:
        return set()
    entities = _jd_entity_tokens(jd_text)
    # If filtering would leave nothing, fall back to single-occurrence allowed
    # (very short JDs where every token appears once).
    filtered = [(t, c) for t, c in counts.items() if t not in entities and c >= min_freq]
    if not filtered:
        filtered = [(t, c) for t, c in counts.items() if t not in entities]
    filtered.sort(key=lambda x: (-x[1], x[0]))
    return {t for t, _ in filtered[:k]}


def _fuzzy_coverage(top_jd: set, resume_tokens: set, threshold: int = 85) -> set:
    """Tokens in top_jd that are present in resume_tokens either exactly or
    via rapidfuzz.ratio >= threshold. Catches typos and abbreviation forms
    the alias map missed."""
    if not top_jd:
        return set()
    if not resume_tokens:
        return set()
    exact = top_jd & resume_tokens
    leftover = top_jd - exact
    if not leftover:
        return exact
    try:
        from rapidfuzz import fuzz
    except Exception:
        return exact
    resume_list = list(resume_tokens)
    fuzzy_hits: set = set()
    for jd_tok in leftover:
        for r_tok in resume_list:
            if fuzz.ratio(jd_tok, r_tok) >= threshold:
                fuzzy_hits.add(jd_tok)
                break
    return exact | fuzzy_hits


# Multi-word tech skills matched as units (not split into individual tokens).
# Shared by hybrid_scorer (ngram signal) and orchestrator (injection).
_NGRAM_SKILLS: frozenset[str] = frozenset({
    # ML / AI
    "machine learning", "deep learning", "natural language processing",
    "computer vision", "large language models", "reinforcement learning",
    "generative ai", "neural networks", "transfer learning",
    "convolutional neural", "transformer model", "foundation model",
    # Data
    "data engineering", "data science", "data analysis", "data pipeline",
    "data warehouse", "data lake", "etl pipeline", "feature engineering",
    "real time processing", "stream processing", "batch processing",
    # Engineering practices
    "test driven development", "behavior driven development",
    "continuous integration", "continuous deployment", "continuous delivery",
    "agile methodology", "system design", "design patterns",
    "microservices architecture", "event driven architecture",
    "object oriented programming", "domain driven design",
    "distributed systems", "high availability", "fault tolerance",
    # APIs / infra
    "rest api", "restful api", "cloud native", "cloud computing",
    "infrastructure as code", "site reliability", "ci cd",
    "service mesh", "api gateway",
})


def extract_jd_ngrams(jd_text: str) -> frozenset[str]:
    """Return multi-word skills from _NGRAM_SKILLS present in the JD."""
    lower = jd_text.lower()
    return frozenset(ng for ng in _NGRAM_SKILLS if ng in lower)


def extract_resume_ngrams(resume_text: str) -> frozenset[str]:
    """Return multi-word skills from _NGRAM_SKILLS present in the resume."""
    lower = resume_text.lower()
    return frozenset(ng for ng in _NGRAM_SKILLS if ng in lower)


# Regex patterns to detect required / preferred section boundaries in JDs.
_REQ_HEADER = re.compile(
    r'(?:^|\n)\s*(?:requirements?|required(?:\s+skills?)?|must[\s-]have|essential'
    r'|minimum\s+qualifications?|basic\s+qualifications?)\s*[:\-]?\s*(?:\n|$)',
    re.IGNORECASE,
)
_PREF_HEADER = re.compile(
    r'(?:^|\n)\s*(?:preferred(?:\s+skills?|qualifications?)?|nice[\s-]to[\s-]have'
    r'|bonus|desired(?:\s+skills?)?|plus(?:\s+points?)?|additional\s+qualifications?)\s*[:\-]?\s*(?:\n|$)',
    re.IGNORECASE,
)
# Any section-like header (catches transitions between sections).
_ANY_HEADER = re.compile(
    r'(?:^|\n)\s*(?:[A-Z][A-Za-z ]{2,30})\s*[:\-]\s*(?:\n|$)',
)


def parse_jd_required_preferred(jd_text: str) -> tuple[str, str]:
    """Split JD into (required_text, preferred_text).

    Looks for explicit 'Required' / 'Preferred' section headers.
    Returns (full_text, '') when no explicit sections found — preserves
    backward-compatible behavior (caller treats entire JD as required).
    """
    req_m = _REQ_HEADER.search(jd_text)
    pref_m = _PREF_HEADER.search(jd_text)

    if not req_m and not pref_m:
        return (jd_text, "")

    # Both sections found — extract each block until the next section header.
    def _block_after(match: re.Match, text: str) -> str:
        start = match.end()
        # Find the next section-like header after this one.
        next_h = _REQ_HEADER.search(text, start) or _PREF_HEADER.search(text, start)
        end = next_h.start() if next_h else len(text)
        return text[start:end].strip()

    if req_m and pref_m:
        req_text = _block_after(req_m, jd_text)
        pref_text = _block_after(pref_m, jd_text)
        return (req_text or jd_text, pref_text)

    if req_m:
        req_text = _block_after(req_m, jd_text)
        return (req_text or jd_text, "")

    # Only preferred found — everything else is "required".
    pref_text = _block_after(pref_m, jd_text)
    before = jd_text[: pref_m.start()].strip()
    return (before or jd_text, pref_text)
