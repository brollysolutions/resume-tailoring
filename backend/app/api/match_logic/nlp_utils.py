"""
NLP utilities: skill extraction, BM25 ranking, and tokenization.
"""

import re
from collections import Counter
from typing import List
from app.core.keyword_utils import _significant_tokens, _STOPWORDS

# Lightweight skill dictionary (tech stack common across job descriptions)
# Normalized form (no spaces, canonical names).
_TECH_SKILLS = {
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "ruby", "php", "kotlin",
    "scala", "swift", "objective-c", "r", "matlab", "sql", "bash", "powershell",
    # Web frameworks
    "react", "vue", "angular", "nextjs", "svelte", "django", "flask", "fastapi", "springboot",
    "nestjs", "rails", "laravel", "asp.net", "expressjs",
    # Databases
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "cassandra", "dynamodb",
    "firestore", "sqlite", "mariadb", "oracle", "snowflake",
    # Cloud & DevOps
    "aws", "gcp", "azure", "kubernetes", "docker", "terraform", "jenkins", "gitlab", "github",
    "circleci", "travis", "heroku", "vercel", "cloudflare",
    # Big Data & ML
    "spark", "hadoop", "kafka", "airflow", "pandas", "numpy", "scikit-learn", "tensorflow",
    "pytorch", "keras", "xgboost", "nlp", "machinelearning", "deeplearning", "ai", "llm",
    # Messaging & Queues
    "rabbitmq", "mqtt", "amqp", "sqs", "pubsub", "kinesis",
    # Monitoring & Observability
    "prometheus", "grafana", "datadog", "newrelic", "splunk", "elk", "logstash", "kibana",
    # Version Control
    "git", "svn", "mercurial",
    # QA & Testing
    "junit", "pytest", "jest", "rspec", "selenium", "cypress", "postman", "jira",
    # Soft skills (for context)
    "communication", "leadership", "agile", "scrum", "kanban", "devops",
}


def extract_skills(text: str) -> set[str]:
    """Extract recognized tech skills from text (case-insensitive).
    Uses the canonical normalization pipeline from keyword_utils."""
    from app.core.keyword_utils import _significant_tokens
    tokens = _significant_tokens(text)
    return tokens & _TECH_SKILLS


def is_known_tech(token: str) -> bool:
    """True if a single token is a recognized technology — in the skill
    dictionary or the skill→domain taxonomy. Used to keep raw JD noise tokens
    (generic words, undefined acronyms) out of project tech stacks."""
    from app.core.skill_taxonomy import domain_of
    norm = (token or "").strip().lower()
    if not norm:
        return False
    return norm in _TECH_SKILLS or domain_of(token) is not None


class BM25Ranker:
    """BM25 ranking algorithm for keyword overlap.

    Used to score how well a resume matches JD requirements.
    More efficient than LLM-based scoring, works offline.
    """

    def __init__(self, documents: List[str], k1: float = 1.5, b: float = 0.75):
        """Initialize BM25 with documents.

        Args:
            documents: List of text documents (e.g., resume sections, JD text)
            k1: Tuning parameter (controls term frequency saturation). Default 1.5.
            b: Tuning parameter (controls document length normalization). Default 0.75.
        """
        self.k1 = k1
        self.b = b
        self.documents = documents
        self.idf = {}
        self.doc_freqs = []
        self.avgdl = 0.0
        self._initialize()

    def _initialize(self):
        """Compute IDF and document frequency statistics."""
        num_docs = len(self.documents)
        all_tokens = set()

        for doc in self.documents:
            tokens = set(_significant_tokens(doc))
            self.doc_freqs.append(Counter(_significant_tokens(doc)))
            all_tokens.update(tokens)

        # Compute IDF for each token
        for token in all_tokens:
            docs_with_token = sum(1 for freq in self.doc_freqs if freq[token] > 0)
            self.idf[token] = max(0.0, (num_docs - docs_with_token + 0.5) / (docs_with_token + 0.5))

        # Average document length
        total_tokens = sum(len(freq) for freq in self.doc_freqs)
        self.avgdl = total_tokens / num_docs if num_docs > 0 else 0

    def score_query(self, query_tokens: List[str], doc_index: int) -> float:
        """Score a document against a query using BM25.

        Args:
            query_tokens: Tokenized query (list of strings)
            doc_index: Index of document to score

        Returns:
            BM25 score (higher = better match)
        """
        if doc_index >= len(self.doc_freqs):
            return 0.0

        doc_freq = self.doc_freqs[doc_index]
        doc_len = sum(doc_freq.values())
        score = 0.0

        for token in query_tokens:
            if token not in self.idf:
                continue

            freq = doc_freq.get(token, 0)
            if freq == 0:
                continue

            idf = self.idf[token]
            # BM25 formula
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * (doc_len / self.avgdl))
            score += idf * (numerator / denominator)

        return score


def keyword_coverage(jd_text: str, resume_text: str) -> float:
    """Fraction of top JD keywords found in resume (with fuzzy matching).

    Uses _top_jd_tokens so the scoring token set matches what the tailoring
    orchestrator injects (NER-filtered, min_freq>=2). Bridges typos and
    abbreviation variants via rapidfuzz when exact match fails.

    Returns value in [0, 1] where 1.0 = every top JD keyword present in resume.
    """
    from app.core.keyword_utils import _top_jd_tokens, _fuzzy_coverage
    top_jd = _top_jd_tokens(jd_text, k=50)
    if not top_jd:
        return 0.0
    resume_tokens = _significant_tokens(resume_text)
    matched = _fuzzy_coverage(top_jd, resume_tokens, threshold=85)
    return len(matched) / len(top_jd)


# Deprecated alias — kept for one release to avoid breaking importers.
# The function never actually computed BM25 (single-doc IDF is degenerate);
# new code should call keyword_coverage directly.
bm25_keyword_coverage = keyword_coverage
