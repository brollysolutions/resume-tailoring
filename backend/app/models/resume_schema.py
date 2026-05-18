"""
Single source of truth for resume data.

The whole pipeline (extract → tailor → render) operates on this schema.
Once a resume is parsed into this shape, the original PDF/DOCX is no longer
edited — we render fresh PDF/DOCX from the JSON using our own template.
"""
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class ContactInfo(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    website: Optional[str] = None


def _coerce_str_list(v: Any) -> Any:
    """Pre-validation coercion for List[str] fields. The LLM occasionally
    returns null, a single string, or a list containing null/empty values —
    normalize to a clean list of non-empty stripped strings."""
    if v is None:
        return []
    if isinstance(v, str):
        # Single string where a list was expected — wrap it.
        v = v.strip()
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


def _coerce_optional_str(v: Any) -> Any:
    """If the LLM returns a list/dict where a string is expected, coerce it."""
    if v is None:
        return None
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x)
    if not isinstance(v, str):
        return str(v)
    return v


class ExperienceEntry(BaseModel):
    title: str = ""
    company: str = ""
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)

    @field_validator("title", "company", mode="before")
    @classmethod
    def normalize_str_fields(cls, v): return _coerce_optional_str(v) or ""

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

    @field_validator("details", mode="before")
    @classmethod
    def normalize_details(cls, v): return _coerce_str_list(v)


class ProjectEntry(BaseModel):
    name: str = ""
    tech: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("tech", mode="before")
    @classmethod
    def normalize_tech(cls, v):
        if isinstance(v, list):
            return ", ".join(str(x) for x in v if x)
        return v

    @field_validator("bullets", mode="before")
    @classmethod
    def normalize_bullets(cls, v): return _coerce_str_list(v)


class SkillCategory(BaseModel):
    category: str = ""
    skills: List[str] = Field(default_factory=list)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v): return _coerce_optional_str(v) or ""

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, v): return _coerce_str_list(v)


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
    summary: Optional[str] = None
    experience: List[ExperienceEntry] = Field(default_factory=list)
    education: List[EducationEntry] = Field(default_factory=list)
    projects: List[ProjectEntry] = Field(default_factory=list)
    skills: List[SkillCategory] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    publications: List[str] = Field(default_factory=list)
    extra_sections: List[ExtraSection] = Field(default_factory=list)
    section_order: List[str] = Field(default_factory=list)

    @field_validator("experience", "education", "projects", "skills", "extra_sections", mode="before")
    @classmethod
    def normalize_obj_list(cls, v): return _coerce_obj_list(v)

    @field_validator("certifications", "publications", "section_order", mode="before")
    @classmethod
    def normalize_str_lists(cls, v): return _coerce_str_list(v)

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
            sk = data.get("skills")
            if isinstance(sk, list) and sk and all(isinstance(s, str) for s in sk):
                data["skills"] = [{"category": "Skills", "skills": sk}]
        return data
