"""
Single source of truth for visual output. The same Resume object renders to:
  - HTML (for in-browser preview AND as the WeasyPrint PDF source)
  - DOCX (programmatically via python-docx, one builder per template)

HTML templates are loose files in backend/app/templates/ — drop in a new
{template_id}.html to add a template (you'll also need a DOCX builder).

Available templates: modern, classic, academic.
"""
import logging
import os
import re
from io import BytesIO
from typing import Optional, List, Dict
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

from app.models.resume_schema import Resume
from app.core.suggestion_applier import apply_suggestions

TEMPLATES_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "templates")
)

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "modern",
        "name": "Modern",
        "description": "Sans-serif, clean single-column layout. Best for tech and modern roles.",
    },
    {
        "id": "classic",
        "name": "Classic",
        "description": "Serif, traditional centered header. Best for formal industries.",
    },
    {
        "id": "academic",
        "name": "Academic",
        "description": "LaTeX-inspired serif layout with hanging-indent publications. Best for research and academic roles.",
    },
]


def list_templates() -> List[Dict[str, str]]:
    return TEMPLATES


def _resolve_template_id(template_id: Optional[str]) -> str:
    valid = {t["id"] for t in TEMPLATES}
    if template_id and template_id in valid:
        return template_id
    return "modern"


# ---------------------------------------------------------------------------
# Layout density — adaptive sizing/margins/spacing
# ---------------------------------------------------------------------------

DENSITY_PRESETS: Dict[str, Dict] = {
    "latex-tight": {
        "margin": "0.5in",
        "margin_inches": 0.5,
        "font_size_pt": 9.5,
        "line_height": 1.12,
        "entry_gap_pt": 2,
        "section_gap_pt": 6,
    },
    "compact": {
        "margin": "0.4in",
        "margin_inches": 0.4,
        "font_size_pt": 10.0,
        "line_height": 1.18,
        "entry_gap_pt": 3,
        "section_gap_pt": 8,
    },
    "standard": {
        "margin": "0.55in",
        "margin_inches": 0.55,
        "font_size_pt": 10.8,
        "line_height": 1.3,
        "entry_gap_pt": 5,
        "section_gap_pt": 11,
    },
    "expanded": {
        "margin": "0.75in",
        "margin_inches": 0.75,
        "font_size_pt": 11.5,
        "line_height": 1.4,
        "entry_gap_pt": 7,
        "section_gap_pt": 14,
    },
}

# Approximate characters-per-page at each density (calibrated empirically).
# Used by _density_for_target_pages to pick the densest preset that fits.
_DENSITY_CAPACITY = {
    "latex-tight": 5500,
    "compact": 4800,
    "standard": 3600,
    "expanded": 2800,
}


def _density_for_target_pages(resume: Resume, target_pages: int) -> str:
    """Pick the LEAST dense preset whose total capacity covers the resume.

    target_pages=1 → squeeze hardest; 2 → moderate; 3+ → relaxed.
    """
    if target_pages < 1:
        target_pages = 1
    content_chars = _resume_char_count(resume)
    # Try presets from loosest to tightest; pick first that fits target_pages
    for preset in ("expanded", "standard", "compact", "latex-tight"):
        if content_chars <= _DENSITY_CAPACITY[preset] * target_pages:
            return preset
    return "latex-tight"


def _resume_char_count(resume: Resume) -> int:
    count = 0
    if resume.summary:
        count += len(resume.summary)
    for e in resume.experience:
        count += len(e.title or "") + len(e.company or "")
        count += sum(len(b) for b in (e.bullets or []))
    for p in resume.projects:
        count += len(p.name or "") + sum(len(b) for b in (p.bullets or []))
    for ed in resume.education:
        count += len(ed.institution or "") + len(ed.degree or "")
        count += sum(len(d) for d in (ed.details or []))
    for s in resume.skills:
        count += sum(len(sk) for sk in (s.skills or []))
    count += sum(len(c) for c in resume.certifications)
    count += sum(len(p.title or "") + len(p.authors or "") + len(p.venue or "") for p in resume.publications)
    count += sum(len(a.title or "") + len(a.description or "") for a in resume.awards)
    count += sum(len(v.role or "") + len(v.organization or "") + sum(len(b) for b in (v.bullets or [])) for v in resume.volunteer)
    count += sum(len(p.title or "") for p in resume.patents)
    count += sum(len(t.title or "") for t in resume.talks)
    count += sum(len(l.name or "") for l in resume.languages)
    return count


def _resolve_density(layout_density: Optional[str]) -> str:
    if layout_density in DENSITY_PRESETS:
        return layout_density
    return "standard"


def _estimate_density(resume: Resume) -> str:
    """Heuristic auto-detection: count content volume → pick density preset.

    <2000 chars → expanded (lots of whitespace)
    2000-5000 chars → standard
    >5000 chars → compact (fit more per page)
    """
    char_count = 0
    section_count = 0

    if resume.summary:
        char_count += len(resume.summary)
        section_count += 1
    for e in resume.experience:
        char_count += len(e.title or "") + len(e.company or "")
        char_count += sum(len(b) for b in (e.bullets or []))
        if e.bullets:
            section_count += 0  # experience counted once below
    if resume.experience:
        section_count += 1
    for p in resume.projects:
        char_count += len(p.name or "") + sum(len(b) for b in (p.bullets or []))
    if resume.projects:
        section_count += 1
    for ed in resume.education:
        char_count += len(ed.institution or "") + len(ed.degree or "")
        char_count += sum(len(d) for d in (ed.details or []))
    if resume.education:
        section_count += 1
    for s in resume.skills:
        char_count += sum(len(sk) for sk in (s.skills or []))
    if resume.skills:
        section_count += 1
    char_count += sum(len(c) for c in resume.certifications)
    char_count += sum(len(p.title or "") + len(p.authors or "") for p in resume.publications)
    char_count += sum(len(a.title or "") + len(a.description or "") for a in resume.awards)
    char_count += sum(len(v.role or "") + sum(len(b) for b in (v.bullets or [])) for v in resume.volunteer)
    for sec in (resume.publications, resume.awards, resume.languages,
                resume.volunteer, resume.patents, resume.talks, resume.certifications):
        if sec:
            section_count += 1

    if char_count < 2000 and section_count < 4:
        return "expanded"
    if char_count > 5000:
        return "compact"
    return "standard"


# ---------------------------------------------------------------------------
# HTML & PDF
# ---------------------------------------------------------------------------

def _pick_density(resume: Resume, layout_density: Optional[str], target_pages: Optional[int]) -> str:
    if layout_density and layout_density in DENSITY_PRESETS:
        return layout_density
    if target_pages and target_pages >= 1:
        return _density_for_target_pages(resume, target_pages)
    return _estimate_density(resume)


def render_html(
    resume: Resume,
    template_id: Optional[str] = "modern",
    highlight_edits: Optional[List[Dict]] = None,
    layout_density: Optional[str] = None,
    target_pages: Optional[int] = None,
) -> str:
    tid = _resolve_template_id(template_id)
    density_key = _pick_density(resume, layout_density, target_pages)
    density = DENSITY_PRESETS[density_key]
    template = _env.get_template(f"{tid}.html")
    return template.render(resume=resume, density=density, density_name=density_key)


def render_pdf(resume: Resume, template_id: Optional[str] = "modern",
               layout_density: Optional[str] = None,
               target_pages: Optional[int] = None) -> bytes:
    from weasyprint import HTML
    html = render_html(resume, template_id, layout_density=layout_density, target_pages=target_pages)
    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# DOCX — built programmatically. One function per template.
# ---------------------------------------------------------------------------

def _doc_width(doc):
    section = doc.sections[0]
    return section.page_width - section.left_margin - section.right_margin


def _set_section_heading_border(paragraph, color="000000"):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _two_col_row(doc, left: str, right: str, *, bold_left=False, italic_left=False,
                 italic_right=False, size=10.5):
    from docx.shared import Pt
    from docx.enum.text import WD_TAB_ALIGNMENT
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.tab_stops.add_tab_stop(_doc_width(doc), alignment=WD_TAB_ALIGNMENT.RIGHT)
    lr = p.add_run(left)
    lr.bold = bold_left
    lr.italic = italic_left
    lr.font.size = Pt(size)
    if right:
        p.add_run("\t")
        rr = p.add_run(right)
        rr.italic = italic_right
        rr.font.size = Pt(size)
    return p


def _bullet(doc, text: str, *, size=10.5):
    from docx.shared import Pt
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(1)
    run = p.add_run(text)
    run.font.size = Pt(size)


def _contact_line(resume: Resume) -> str:
    parts = [v for v in [
        resume.contact.phone, resume.contact.email, resume.contact.location,
        resume.contact.linkedin, resume.contact.github, resume.contact.website,
    ] if v]
    return "  ·  ".join(parts)


_DEFAULT_ORDER = ["summary", "experience", "projects", "education", "skills", "certifications"]


def _render_extra_section_docx(doc, extra, section_heading_fn, size=10.5):
    from docx.shared import Pt
    section_heading_fn(extra.title)
    for item in extra.items:
        if extra.content_type == "entries":
            if item.header:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                r = p.add_run(item.header)
                r.bold = True
                r.font.size = Pt(size)
            if item.subheader:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                p.add_run(item.subheader).font.size = Pt(size)
            if item.text:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                p.add_run(item.text).font.size = Pt(size)
            for b in item.bullets:
                _bullet(doc, b, size=size)
        elif extra.content_type in ("list", "text"):
            text = item.text or item.header or ""
            if text:
                _bullet(doc, text, size=size)


# --- Generic DOCX renderers for new section types -------------------------

def _render_publication_docx(doc, pub, *, size=10.5):
    """Hanging-indent citation block."""
    from docx.shared import Pt
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Pt(16)
    p.paragraph_format.first_line_indent = Pt(-16)
    parts = []
    if pub.authors: parts.append(f"{pub.authors}.")
    if pub.year: parts.append(f"({pub.year}).")
    title = pub.title or ""
    if title and not title.endswith("."): title += "."
    if title: parts.append(title)
    txt_pre = " ".join(parts)
    if txt_pre:
        p.add_run(txt_pre + (" " if pub.venue else "")).font.size = Pt(size)
    if pub.venue:
        ven = p.add_run(pub.venue + ".")
        ven.italic = True
        ven.font.size = Pt(size)
    if pub.doi:
        p.add_run(f" DOI: {pub.doi}.").font.size = Pt(size)
    if pub.url:
        p.add_run(f" {pub.url}").font.size = Pt(size)


def _render_award_docx(doc, award, *, size=10.5):
    from docx.shared import Pt
    date = award.date or ""
    _two_col_row(doc, award.title or "", date, bold_left=True, italic_right=True, size=size)
    if award.issuer:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        r = p.add_run(award.issuer)
        r.italic = True
        r.font.size = Pt(size - 0.5)
    if award.description:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        p.add_run(award.description).font.size = Pt(size)


def _render_languages_docx(doc, languages, *, size=10.5):
    from docx.shared import Pt
    parts = []
    for l in languages:
        if not l.name:
            continue
        if l.proficiency:
            parts.append(f"{l.name} ({l.proficiency})")
        else:
            parts.append(l.name)
    if parts:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        p.add_run(", ".join(parts)).font.size = Pt(size)


def _render_volunteer_docx(doc, vol, *, size=10.5):
    date = ""
    if vol.start_date or vol.end_date:
        date = f"{vol.start_date or ''}{' – ' if (vol.start_date and vol.end_date) else ''}{vol.end_date or ''}"
    _two_col_row(doc, vol.organization or vol.role, date, bold_left=True, size=size)
    if vol.role and vol.organization:
        _two_col_row(doc, vol.role, vol.location or "", italic_left=True, size=size - 0.5)
    for b in vol.bullets:
        _bullet(doc, b, size=size)


def _render_patent_docx(doc, patent, *, size=10.5):
    from docx.shared import Pt
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Pt(16)
    p.paragraph_format.first_line_indent = Pt(-16)
    title_run = p.add_run(patent.title or "")
    title_run.bold = True
    title_run.font.size = Pt(size)
    extras = []
    if patent.number: extras.append(f"(Patent No. {patent.number})")
    if patent.date: extras.append(f"— {patent.date}")
    if patent.status: extras.append(f"[{patent.status}]")
    if extras:
        p.add_run(" " + " ".join(extras)).font.size = Pt(size)
    if patent.authors:
        auth = p.add_run(f". {patent.authors}")
        auth.italic = True
        auth.font.size = Pt(size)


def _render_talk_docx(doc, talk, *, size=10.5):
    from docx.shared import Pt
    date = talk.date or ""
    _two_col_row(doc, talk.title or "", date, italic_left=True, italic_right=True, size=size)
    if talk.venue or talk.type:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        venue_text = talk.venue or ""
        if talk.type:
            venue_text = (venue_text + " · " if venue_text else "") + talk.type
        r = p.add_run(venue_text)
        r.italic = True
        r.font.size = Pt(size - 0.5)


def _add_page2_header(doc, name: str):
    """Add a right-aligned header (name + page #) that appears on pages 2+ only."""
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    section = doc.sections[0]
    section.different_first_page_header_footer = True
    header = section.header
    # Clear default empty paragraph if present
    p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run(f"{name or ''} — Page ")
    run.font.size = Pt(9)
    # Page number field
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run._r.append(fld_begin)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    run._r.append(instr)
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)


# --- Modern DOCX builder --------------------------------------------------

def _render_docx_modern(resume: Resume, density_key: str = "standard") -> bytes:
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    density = DENSITY_PRESETS[density_key]
    base_size = density["font_size_pt"]
    margin_in = density["margin_inches"]
    section_gap = density["section_gap_pt"]

    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(margin_in)
        section.bottom_margin = Inches(margin_in)
        section.left_margin = Inches(margin_in + 0.05)
        section.right_margin = Inches(margin_in + 0.05)

    _add_page2_header(doc, resume.name or "")

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(base_size)

    # Name (left-aligned, bold)
    name_p = doc.add_paragraph()
    name_p.paragraph_format.space_after = Pt(2)
    nr = name_p.add_run(resume.name or "")
    nr.bold = True
    nr.font.size = Pt(22)

    # Contact with bottom border
    contact = _contact_line(resume)
    if contact:
        cp = doc.add_paragraph()
        cp.paragraph_format.space_after = Pt(8)
        cr = cp.add_run(contact)
        cr.font.size = Pt(9.5)
        cr.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
        _set_section_heading_border(cp, color="d0d0d0")

    def section_heading(text: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(section_gap)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(base_size)
        return p

    _hidden = set(resume.hidden_sections or [])
    for sec in (resume.section_order or _DEFAULT_ORDER):
        if sec in _hidden:
            continue
        if sec == "summary" and resume.summary:
            section_heading("Summary")
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            p.add_run(resume.summary).font.size = Pt(base_size)
        elif sec == "experience" and resume.experience:
            section_heading("Experience")
            for exp in resume.experience:
                date = ""
                if exp.start_date or exp.end_date:
                    date = f"{exp.start_date or ''}{' – ' if (exp.start_date and exp.end_date) else ''}{exp.end_date or ''}"
                _two_col_row(doc, exp.title, date, bold_left=True)
                if exp.company or exp.location:
                    _two_col_row(doc, exp.company or "", exp.location or "", italic_left=True)
                for b in exp.bullets:
                    _bullet(doc, b)
        elif sec == "projects" and resume.projects:
            section_heading("Projects")
            for proj in resume.projects:
                _two_col_row(doc, proj.name, proj.tech or "", bold_left=True)
                for b in proj.bullets:
                    _bullet(doc, b)
        elif sec == "education" and resume.education:
            section_heading("Education")
            for ed in resume.education:
                date = ""
                if ed.start_date or ed.end_date:
                    date = f"{ed.start_date or ''}{' – ' if (ed.start_date and ed.end_date) else ''}{ed.end_date or ''}"
                _two_col_row(doc, ed.institution, date, bold_left=True)
                sub_left = ""
                if ed.degree:
                    sub_left = ed.degree
                if ed.field:
                    sub_left = (sub_left + " in " if sub_left else "") + ed.field
                sub_right = ed.location or ""
                if ed.gpa:
                    sub_right = (sub_right + " · " if sub_right else "") + f"GPA: {ed.gpa}"
                if sub_left or sub_right:
                    _two_col_row(doc, sub_left, sub_right, italic_left=True)
                for d in ed.details:
                    _bullet(doc, d)
        elif sec == "skills" and resume.skills:
            section_heading("Skills")
            for sk in resume.skills:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                cat = p.add_run(f"{sk.category}: ")
                cat.bold = True
                cat.font.size = Pt(10.5)
                val = p.add_run(", ".join(sk.skills))
                val.font.size = Pt(10.5)
        elif sec == "certifications" and resume.certifications:
            section_heading("Certifications")
            for c in resume.certifications:
                _bullet(doc, c)
        elif sec == "publications" and resume.publications:
            section_heading("Publications")
            for pub in resume.publications:
                _render_publication_docx(doc, pub, size=10.5)
        elif sec == "awards" and resume.awards:
            section_heading("Awards")
            for award in resume.awards:
                _render_award_docx(doc, award, size=10.5)
        elif sec == "languages" and resume.languages:
            section_heading("Languages")
            _render_languages_docx(doc, resume.languages, size=10.5)
        elif sec == "volunteer" and resume.volunteer:
            section_heading("Volunteer Experience")
            for vol in resume.volunteer:
                _render_volunteer_docx(doc, vol, size=10.5)
        elif sec == "patents" and resume.patents:
            section_heading("Patents")
            for pat in resume.patents:
                _render_patent_docx(doc, pat, size=10.5)
        elif sec == "talks" and resume.talks:
            section_heading("Talks & Presentations")
            for talk in resume.talks:
                _render_talk_docx(doc, talk, size=10.5)
        elif sec.startswith("extra:"):
            extra_title = sec[6:]
            for extra in resume.extra_sections:
                if extra.title == extra_title:
                    _render_extra_section_docx(doc, extra, section_heading, size=10.5)
                    break

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# --- Classic DOCX builder -------------------------------------------------

def _render_docx_classic(resume: Resume, density_key: str = "standard") -> bytes:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    density = DENSITY_PRESETS[density_key]
    base_size = density["font_size_pt"]
    margin_in = density["margin_inches"]
    section_gap = density["section_gap_pt"]

    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(margin_in)
        section.bottom_margin = Inches(margin_in)
        section.left_margin = Inches(margin_in + 0.05)
        section.right_margin = Inches(margin_in + 0.05)

    _add_page2_header(doc, resume.name or "")

    style = doc.styles["Normal"]
    style.font.name = "Georgia"
    style.font.size = Pt(base_size)

    # Centered name in small caps
    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_p.paragraph_format.space_after = Pt(4)
    nr = name_p.add_run((resume.name or "").upper())
    nr.font.size = Pt(22)

    # Centered italic contact line, with bottom border
    contact = _contact_line(resume)
    if contact:
        cp = doc.add_paragraph()
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.paragraph_format.space_after = Pt(10)
        cr = cp.add_run(contact)
        cr.italic = True
        cr.font.size = Pt(10)
        _set_section_heading_border(cp)

    def section_heading(text: str):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(section_gap)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(base_size + 1.2)
        _set_section_heading_border(p)
        return p

    _hidden = set(resume.hidden_sections or [])
    for sec in (resume.section_order or _DEFAULT_ORDER):
        if sec in _hidden:
            continue
        if sec == "summary" and resume.summary:
            section_heading("Summary")
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.space_after = Pt(2)
            p.add_run(resume.summary).font.size = Pt(11)
        elif sec == "experience" and resume.experience:
            section_heading("Experience")
            for exp in resume.experience:
                date = ""
                if exp.start_date or exp.end_date:
                    date = f"{exp.start_date or ''}{' – ' if (exp.start_date and exp.end_date) else ''}{exp.end_date or ''}"
                _two_col_row(doc, exp.company or exp.title, date, bold_left=True, italic_right=True, size=11)
                if exp.company or exp.location:
                    _two_col_row(doc, exp.title, exp.location or "", italic_left=True, size=10.5)
                for b in exp.bullets:
                    _bullet(doc, b, size=11)
        elif sec == "projects" and resume.projects:
            section_heading("Projects")
            for proj in resume.projects:
                _two_col_row(doc, proj.name, proj.tech or "", bold_left=True, italic_right=True, size=11)
                for b in proj.bullets:
                    _bullet(doc, b, size=11)
        elif sec == "education" and resume.education:
            section_heading("Education")
            for ed in resume.education:
                date = ""
                if ed.start_date or ed.end_date:
                    date = f"{ed.start_date or ''}{' – ' if (ed.start_date and ed.end_date) else ''}{ed.end_date or ''}"
                _two_col_row(doc, ed.institution, date, bold_left=True, italic_right=True, size=11)
                sub_left = ""
                if ed.degree:
                    sub_left = ed.degree
                if ed.field:
                    sub_left = (sub_left + " in " if sub_left else "") + ed.field
                sub_right = ed.location or ""
                if ed.gpa:
                    sub_right = (sub_right + " · " if sub_right else "") + f"GPA: {ed.gpa}"
                if sub_left or sub_right:
                    _two_col_row(doc, sub_left, sub_right, italic_left=True, size=10.5)
                for d in ed.details:
                    _bullet(doc, d, size=11)
        elif sec == "skills" and resume.skills:
            section_heading("Skills")
            for sk in resume.skills:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                cat = p.add_run(f"{sk.category}: ")
                cat.bold = True
                cat.font.size = Pt(11)
                val = p.add_run(", ".join(sk.skills))
                val.font.size = Pt(11)
        elif sec == "certifications" and resume.certifications:
            section_heading("Certifications")
            for c in resume.certifications:
                _bullet(doc, c, size=11)
        elif sec == "publications" and resume.publications:
            section_heading("Publications")
            for pub in resume.publications:
                _render_publication_docx(doc, pub, size=11)
        elif sec == "awards" and resume.awards:
            section_heading("Awards")
            for award in resume.awards:
                _render_award_docx(doc, award, size=11)
        elif sec == "languages" and resume.languages:
            section_heading("Languages")
            _render_languages_docx(doc, resume.languages, size=11)
        elif sec == "volunteer" and resume.volunteer:
            section_heading("Volunteer Experience")
            for vol in resume.volunteer:
                _render_volunteer_docx(doc, vol, size=11)
        elif sec == "patents" and resume.patents:
            section_heading("Patents")
            for pat in resume.patents:
                _render_patent_docx(doc, pat, size=11)
        elif sec == "talks" and resume.talks:
            section_heading("Talks & Presentations")
            for talk in resume.talks:
                _render_talk_docx(doc, talk, size=11)
        elif sec.startswith("extra:"):
            extra_title = sec[6:]
            for extra in resume.extra_sections:
                if extra.title == extra_title:
                    _render_extra_section_docx(doc, extra, section_heading, size=11)
                    break

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# --- Academic DOCX builder ---------------------------------------------------

def _render_docx_academic(resume: Resume, density_key: str = "standard") -> bytes:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    density = DENSITY_PRESETS[density_key]
    base_size = density["font_size_pt"]
    margin_in = density["margin_inches"]
    section_gap = density["section_gap_pt"]

    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(margin_in)
        section.bottom_margin = Inches(margin_in)
        section.left_margin = Inches(margin_in)
        section.right_margin = Inches(margin_in)

    _add_page2_header(doc, resume.name or "")

    style = doc.styles["Normal"]
    style.font.name = "Georgia"
    style.font.size = Pt(base_size)

    # Centered name in small-caps style
    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_p.paragraph_format.space_after = Pt(5)
    nr = name_p.add_run((resume.name or "").upper())
    nr.font.size = Pt(26)
    nr.font.name = "Georgia"

    # Centered contact, bottom border
    contact = _contact_line(resume)
    if contact:
        cp = doc.add_paragraph()
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cp.paragraph_format.space_after = Pt(8)
        cr = cp.add_run(contact)
        cr.font.size = Pt(9.5)
        _set_section_heading_border(cp, color="000000")

    def section_heading(text: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(section_gap + 2)
        p.paragraph_format.space_after = Pt(5)
        r = p.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(base_size + 2)
        r.font.name = "Georgia"
        _set_section_heading_border(p, color="111111")
        return p

    _hidden = set(resume.hidden_sections or [])
    for sec in (resume.section_order or _DEFAULT_ORDER):
        if sec in _hidden:
            continue
        if sec == "summary" and resume.summary:
            section_heading("Summary")
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.space_after = Pt(2)
            p.add_run(resume.summary).font.size = Pt(11)
        elif sec == "experience" and resume.experience:
            section_heading("Work Experience")
            for exp in resume.experience:
                date = ""
                if exp.start_date or exp.end_date:
                    date = f"{exp.start_date or ''}{' – ' if (exp.start_date and exp.end_date) else ''}{exp.end_date or ''}"
                _two_col_row(doc, exp.company or exp.title, date, bold_left=True, italic_right=True, size=11)
                if exp.company:
                    _two_col_row(doc, exp.title, exp.location or "", italic_left=True, size=10.5)
                for b in exp.bullets:
                    _bullet(doc, b, size=11)
        elif sec == "projects" and resume.projects:
            section_heading("Projects")
            for proj in resume.projects:
                _two_col_row(doc, proj.name, proj.tech or "", bold_left=True, italic_right=True, size=11)
                for b in proj.bullets:
                    _bullet(doc, b, size=11)
        elif sec == "education" and resume.education:
            section_heading("Education")
            for ed in resume.education:
                date = ""
                if ed.start_date or ed.end_date:
                    date = f"{ed.start_date or ''}{' – ' if (ed.start_date and ed.end_date) else ''}{ed.end_date or ''}"
                _two_col_row(doc, ed.institution, date, bold_left=True, italic_right=True, size=11)
                sub_left = ""
                if ed.degree:
                    sub_left = ed.degree
                if ed.field:
                    sub_left = (sub_left + " in " if sub_left else "") + ed.field
                sub_right = ed.location or ""
                if ed.gpa:
                    sub_right = (sub_right + " · " if sub_right else "") + f"GPA: {ed.gpa}"
                if sub_left or sub_right:
                    _two_col_row(doc, sub_left, sub_right, italic_left=True, size=10.5)
                for d in ed.details:
                    _bullet(doc, d, size=11)
        elif sec == "skills" and resume.skills:
            section_heading("Skills")
            for sk in resume.skills:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(1)
                cat = p.add_run(f"{sk.category}: ")
                cat.bold = True
                cat.font.size = Pt(11)
                val = p.add_run(", ".join(sk.skills))
                val.font.size = Pt(11)
        elif sec == "certifications" and resume.certifications:
            section_heading("Certifications")
            for c in resume.certifications:
                _bullet(doc, c, size=11)
        elif sec == "publications" and resume.publications:
            section_heading("Publications")
            for pub in resume.publications:
                _render_publication_docx(doc, pub, size=11)
        elif sec == "awards" and resume.awards:
            section_heading("Awards & Honors")
            for award in resume.awards:
                _render_award_docx(doc, award, size=11)
        elif sec == "languages" and resume.languages:
            section_heading("Languages")
            _render_languages_docx(doc, resume.languages, size=11)
        elif sec == "volunteer" and resume.volunteer:
            section_heading("Volunteer Experience")
            for vol in resume.volunteer:
                _render_volunteer_docx(doc, vol, size=11)
        elif sec == "patents" and resume.patents:
            section_heading("Patents")
            for pat in resume.patents:
                _render_patent_docx(doc, pat, size=11)
        elif sec == "talks" and resume.talks:
            section_heading("Talks & Presentations")
            for talk in resume.talks:
                _render_talk_docx(doc, talk, size=11)
        elif sec.startswith("extra:"):
            extra_title = sec[6:]
            for extra in resume.extra_sections:
                if extra.title == extra_title:
                    _render_extra_section_docx(doc, extra, section_heading, size=11)
                    break

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


_DOCX_BUILDERS = {
    "modern": _render_docx_modern,
    "classic": _render_docx_classic,
    "academic": _render_docx_academic,
}


def render_docx(resume: Resume, template_id: Optional[str] = "modern",
                layout_density: Optional[str] = None,
                target_pages: Optional[int] = None) -> bytes:
    builder = _DOCX_BUILDERS.get(_resolve_template_id(template_id), _render_docx_modern)
    density_key = _pick_density(resume, layout_density, target_pages)
    return builder(resume, density_key)

def resume_to_plaintext(resume: Resume) -> str:
    """Convert Resume object to plaintext representation."""
    lines = [resume.name or ""]
    parts = [v for v in [
        resume.contact.phone, resume.contact.email, resume.contact.location,
        resume.contact.linkedin, resume.contact.github, resume.contact.website,
    ] if v]
    if parts:
        lines.append(" | ".join(parts))

    _hidden = set(resume.hidden_sections or [])
    for sec in (resume.section_order or _DEFAULT_ORDER):
        if sec in _hidden:
            continue
        if sec == "summary" and resume.summary:
            lines += ["", "SUMMARY", resume.summary]
        elif sec == "experience" and resume.experience:
            lines += ["", "EXPERIENCE"]
            for e in resume.experience:
                head = f"{e.title} @ {e.company}"
                if e.start_date or e.end_date:
                    head += f"  [{e.start_date or ''} – {e.end_date or ''}]"
                if e.location:
                    head += f"  ({e.location})"
                lines.append(head)
                for b in (e.bullets or []):
                    lines.append(f"- {b}")
        elif sec == "projects" and resume.projects:
            lines += ["", "PROJECTS"]
            for p in resume.projects:
                lines.append(f"{p.name}" + (f" — {p.tech}" if p.tech else ""))
                for b in (p.bullets or []):
                    lines.append(f"- {b}")
        elif sec == "education" and resume.education:
            lines += ["", "EDUCATION"]
            for ed in resume.education:
                head = ed.institution
                if ed.degree or ed.field:
                    head += f" — {ed.degree or ''} {('in ' + ed.field) if ed.field else ''}".strip()
                if ed.start_date or ed.end_date:
                    head += f"  [{ed.start_date or ''} – {ed.end_date or ''}]"
                lines.append(head)
                for d in (ed.details or []):
                    lines.append(f"- {d}")
        elif sec == "skills" and resume.skills:
            lines += ["", "SKILLS"]
            for sk in resume.skills:
                lines.append(f"{sk.category}: {', '.join(sk.skills or [])}")
        elif sec == "certifications" and resume.certifications:
            lines += ["", "CERTIFICATIONS"]
            for c in (resume.certifications or []):
                lines.append(f"- {c}")
        elif sec.startswith("extra:"):
            extra_title = sec[6:]
            for extra in resume.extra_sections:
                if extra.title == extra_title:
                    lines += ["", extra.title.upper()]
                    for item in extra.items:
                        if item.header:
                            lines.append(item.header + (f" — {item.subheader}" if item.subheader else ""))
                        if item.text:
                            lines.append(item.text)
                        for b in item.bullets:
                            lines.append(f"- {b}")
                    break

    return "\n".join(lines)
