"""
Single source of truth for resume data.

The whole pipeline (extract → tailor → render) operates on this schema.
Once a resume is parsed into this shape, the original PDF/DOCX is no longer
edited — we render fresh PDF/DOCX from the JSON using our own template.
"""
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from app.core.url_utils import normalize_url

# Words that should never appear as standalone entries in a project's tech field.
# Catches both extraction-path contamination and LLM keyword-injection leakage.
_TECH_FIELD_NOISE = frozenset({
    "along", "around", "across", "within", "throughout",
    "banking", "basis", "capability", "capabilities", "center", "centres",
    "change", "changes", "agreement", "agreements",
    "accountability", "accountable",
    "cfos", "cfo", "cto", "coo", "cpos",
    "financial", "finance", "budget", "budgeting",
    "expense", "expenses", "revenue", "revenues",
    "forecast", "forecasting", "reporting",
    "compliance", "governance", "audit", "auditing",
    "operations", "operational", "strategy", "strategic",
    "initiative", "initiatives", "program", "programs",
    "customer", "customers", "client", "clients",
    "product", "products",
    "market", "markets", "business", "businesses",
    "dataset", "datasets", "insight", "insights",
    "dashboard", "dashboards",
    "meeting", "meetings", "presentation", "presentations",
})


class CustomLink(BaseModel):
    label: str = ""
    url: str = ""

    @field_validator("label", "url", mode="before")
    @classmethod
    def normalize_str_fields(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("url", mode="after")
    @classmethod
    def _normalize_urls(cls, v): return normalize_url(v)


class ContactInfo(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None

    @field_validator("email", "phone", "location", "linkedin", "github", "website", mode="before")
    @classmethod
    def _strip_nulls(cls, v):
        val = _coerce_optional_str(v)
        if val and isinstance(val, str) and val.lower().startswith("mailto:"):
            return val[7:].strip()
        return val

    @field_validator("linkedin", "github", "website", mode="after")
    @classmethod
    def _normalize_urls(cls, v): return normalize_url(v)


import re

def _coerce_str_list(v: Any) -> Any:
    """Pre-validation coercion for List[str] fields. The LLM occasionally
    returns null, a single string, or a list containing null/empty values —
    normalize to a clean list of non-empty stripped strings.
    Also strips leading bullet characters (- , * , • , — , ·) to prevent double bullets."""
    if v is None:
        return []
    if isinstance(v, str):
        v = v.strip()
        # Strip leading bullet chars
        v = re.sub(r"^[•\-\*—·‒–]\s*", "", v)
        return [v] if v else []
    if not isinstance(v, list):
        return v
    cleaned = []
    for s in v:
        if s is None:
            continue
        if not isinstance(s, str):
            s = str(s)
        s = s.strip()
        # Strip leading bullet chars
        s = re.sub(r"^[•\-\*—·‒–]\s*", "", s)
        if s:
            cleaned.append(s)
    return cleaned


def _coerce_obj_list(v: Any) -> Any:
    """Pre-validation coercion for List[Model] fields. Drops None entries
    and converts null → []."""
    if v is None:
        return []
    if isinstance(v, list):
        return [x for x in v if x is not None]
    return v


_NULL_SENTINEL_STRINGS = {"", "null", "none", "n/a", "na", "undefined", "nan", "unknown"}


def _coerce_optional_str(v: Any) -> Any:
    """If the LLM returns a list/dict where a string is expected, coerce it.
    Also collapse literal null-sentinel strings ("null", "None", "N/A", "") → None
    so downstream templates don't render them as text."""
    if v is None:
        return None
    if isinstance(v, list):
        v = " ".join(str(x) for x in v if x)
    elif not isinstance(v, str):
        v = str(v)
    stripped = v.strip()
    if stripped.lower() in _NULL_SENTINEL_STRINGS:
        return None
    return stripped


class ExperienceEntry(BaseModel):
    title: str = ""
    company: str = ""
    company_url: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)

    @field_validator("title", "company", mode="before")
    @classmethod
    def normalize_str_fields(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("location", "start_date", "end_date", "company_url", mode="before")
    @classmethod
    def _strip_nulls(cls, v): return _coerce_optional_str(v)

    @field_validator("company_url", mode="after")
    @classmethod
    def _normalize_urls(cls, v): return normalize_url(v)

    @field_validator("bullets", mode="before")
    @classmethod
    def normalize_bullets(cls, v): return _coerce_str_list(v)


class EducationEntry(BaseModel):
    institution: str = ""
    degree: Optional[str] = None
    field: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    details: List[str] = Field(default_factory=list)

    @field_validator("institution", mode="before")
    @classmethod
    def normalize_institution(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("degree", "field", "location", "start_date", "end_date", "gpa", mode="before")
    @classmethod
    def _strip_nulls(cls, v): return _coerce_optional_str(v)

    @field_validator("details", mode="before")
    @classmethod
    def normalize_details(cls, v): return _coerce_str_list(v)


class ProjectEntry(BaseModel):
    name: str = ""
    tech: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None
    demo_url: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("tech", mode="before")
    @classmethod
    def normalize_tech(cls, v):
        if isinstance(v, list):
            items = [str(x).strip() for x in v if x]
        elif isinstance(v, str):
            items = [x.strip() for x in v.split(",") if x.strip()]
        else:
            return _coerce_optional_str(v)
        filtered = [t for t in items if t.lower() not in _TECH_FIELD_NOISE]
        return _coerce_optional_str(", ".join(filtered)) if filtered else None

    @field_validator("date", "url", "demo_url", mode="before")
    @classmethod
    def _strip_date_null(cls, v): return _coerce_optional_str(v)

    @field_validator("url", "demo_url", mode="after")
    @classmethod
    def _normalize_urls(cls, v): return normalize_url(v)

    @field_validator("bullets", mode="before")
    @classmethod
    def normalize_bullets(cls, v): return _coerce_str_list(v)


class SkillCategory(BaseModel):
    category: str = ""
    skills: List[str] = Field(default_factory=list)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v):
        s = _coerce_optional_str(v) or ""
        return s.rstrip(": ").rstrip()

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, v): return _coerce_str_list(v)


class Certification(BaseModel):
    name: str = ""
    issuer: Optional[str] = None
    date: Optional[str] = None
    credential_url: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("issuer", "date", "credential_url", mode="before")
    @classmethod
    def _strip_nulls(cls, v): return _coerce_optional_str(v)

    @field_validator("credential_url", mode="after")
    @classmethod
    def _normalize_urls(cls, v): return normalize_url(v)


class Publication(BaseModel):
    title: str = ""
    authors: Optional[str] = None
    venue: Optional[str] = None
    year: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("doi", "url", mode="after")
    @classmethod
    def _normalize_urls(cls, v): return normalize_url(v)


class Award(BaseModel):
    title: str = ""
    issuer: Optional[str] = None
    date: Optional[str] = None
    description: Optional[str] = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, v): return _coerce_optional_str(v) or ""


class Language(BaseModel):
    name: str = ""
    proficiency: Optional[str] = None  # Native | Fluent | Conversational | Basic

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v): return _coerce_optional_str(v) or ""


class VolunteerEntry(BaseModel):
    role: str = ""
    organization: str = ""
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)

    @field_validator("role", "organization", mode="before")
    @classmethod
    def normalize_str_fields(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("bullets", mode="before")
    @classmethod
    def normalize_bullets(cls, v): return _coerce_str_list(v)


class Patent(BaseModel):
    title: str = ""
    number: Optional[str] = None
    date: Optional[str] = None
    status: Optional[str] = None  # Pending | Granted
    authors: Optional[str] = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, v): return _coerce_optional_str(v) or ""


class Talk(BaseModel):
    title: str = ""
    venue: Optional[str] = None
    date: Optional[str] = None
    type: Optional[str] = None  # Conference | Workshop | Seminar

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, v): return _coerce_optional_str(v) or ""


def _coerce_publication_list(v: Any) -> Any:
    """Coerce publications: legacy List[str] → List[Publication(title=s)]."""
    if v is None:
        return []
    if not isinstance(v, list):
        return v
    out = []
    for item in v:
        if item is None:
            continue
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append({"title": s})
        elif isinstance(item, dict):
            out.append(item)
    return out


def _coerce_certification_list(v: Any) -> Any:
    """Coerce certifications: legacy List[str] → List[Certification(name=s)]."""
    if v is None:
        return []
    if not isinstance(v, list):
        return v
    out = []
    for item in v:
        if item is None:
            continue
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append({"name": s})
        elif isinstance(item, dict):
            out.append(item)
    return out


class SectionItem(BaseModel):
    header: Optional[str] = None
    subheader: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)
    text: Optional[str] = None

    @field_validator("bullets", mode="before")
    @classmethod
    def normalize_bullets(cls, v): return _coerce_str_list(v)


class ExtraSection(BaseModel):
    title: str
    content_type: Literal["entries", "text", "list"] = "entries"
    items: List[SectionItem] = Field(default_factory=list)

    @field_validator("content_type", mode="before")
    @classmethod
    def normalize_content_type(cls, v):
        return v if v in ("entries", "text", "list") else "entries"

    @field_validator("items", mode="before")
    @classmethod
    def normalize_items(cls, v): return _coerce_obj_list(v)


class Resume(BaseModel):
    name: str = ""
    contact: ContactInfo = Field(default_factory=ContactInfo)
    custom_links: List[CustomLink] = Field(default_factory=list)
    summary: Optional[str] = None
    experience: List[ExperienceEntry] = Field(default_factory=list)
    education: List[EducationEntry] = Field(default_factory=list)
    projects: List[ProjectEntry] = Field(default_factory=list)
    skills: List[SkillCategory] = Field(default_factory=list)
    certifications: List[Certification] = Field(default_factory=list)
    publications: List[Publication] = Field(default_factory=list)
    awards: List[Award] = Field(default_factory=list)
    languages: List[Language] = Field(default_factory=list)
    volunteer: List[VolunteerEntry] = Field(default_factory=list)
    patents: List[Patent] = Field(default_factory=list)
    talks: List[Talk] = Field(default_factory=list)
    extra_sections: List[ExtraSection] = Field(default_factory=list)
    section_order: List[str] = Field(default_factory=list)
    hidden_sections: List[str] = Field(default_factory=list)

    @field_validator(
        "experience", "education", "projects", "skills",
        "awards", "languages", "volunteer", "patents", "talks",
        "extra_sections", "custom_links",
        mode="before",
    )
    @classmethod
    def normalize_obj_list(cls, v): return _coerce_obj_list(v)

    @field_validator("publications", mode="before")
    @classmethod
    def normalize_publications(cls, v): return _coerce_publication_list(v)

    @field_validator("certifications", mode="before")
    @classmethod
    def normalize_certifications(cls, v): return _coerce_certification_list(v)

    @field_validator("section_order", "hidden_sections", mode="before")
    @classmethod
    def normalize_str_lists(cls, v): return _coerce_str_list(v)

    # Drop placeholder/empty entries the LLM sometimes emits when a section is
    # absent (e.g., [{"name": "", "proficiency": null}] instead of []). Without
    # these, templates render heading + blank content.
    @field_validator("publications", mode="after")
    @classmethod
    def filter_empty_publications(cls, v): return [p for p in v if (p.title or "").strip()]

    @field_validator("certifications", mode="after")
    @classmethod
    def filter_empty_certifications(cls, v): return [c for c in v if (c.name or "").strip()]

    @field_validator("awards", mode="after")
    @classmethod
    def filter_empty_awards(cls, v): return [a for a in v if (a.title or "").strip()]

    @field_validator("languages", mode="after")
    @classmethod
    def filter_empty_languages(cls, v): return [l for l in v if (l.name or "").strip()]

    @field_validator("volunteer", mode="after")
    @classmethod
    def filter_empty_volunteer(cls, v): return [x for x in v if (x.role or "").strip() or (x.organization or "").strip()]

    @field_validator("patents", mode="after")
    @classmethod
    def filter_empty_patents(cls, v): return [p for p in v if (p.title or "").strip()]

    @field_validator("talks", mode="after")
    @classmethod
    def filter_empty_talks(cls, v): return [t for t in v if (t.title or "").strip()]

    @field_validator("skills", mode="after")
    @classmethod
    def filter_empty_skills(cls, v):
        """Drop categories that have no skills (harmless but cleans up render)."""
        return [s for s in v if s.skills]

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v): return "" if v is None else v

    @field_validator("summary", mode="before")
    @classmethod
    def normalize_summary(cls, v): return _coerce_optional_str(v)

    @model_validator(mode="before")
    @classmethod
    def normalize_resume_shape(cls, data):
        if isinstance(data, dict):
            if data.get("contact") is None:
                data["contact"] = {}
            # If skills was returned as a flat list of strings instead of
            # [{"category": ..., "skills": [...]}], wrap it into one category.
            # Use empty category string as sentinel for "flat layout".
            sk = data.get("skills")
            if isinstance(sk, list) and sk:
                if all(isinstance(s, str) for s in sk):
                    data["skills"] = [{"category": "", "skills": sk}]
                elif len(sk) == 1 and isinstance(sk[0], dict) and (sk[0].get("category") or "").lower() == "skills":
                    # If LLM returned exactly one category named "Skills", treat as flat.
                    sk[0]["category"] = ""
        return data
