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
# HTML & PDF
# ---------------------------------------------------------------------------

def render_html(
    resume: Resume,
    template_id: Optional[str] = "modern",
    highlight_edits: Optional[List[Dict]] = None,
) -> str:
    tid = _resolve_template_id(template_id)
    template = _env.get_template(f"{tid}.html")
    return template.render(resume=resume)


def render_pdf(resume: Resume, template_id: Optional[str] = "modern") -> bytes:
    from weasyprint import HTML
    html = render_html(resume, template_id)
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


# --- Modern DOCX builder --------------------------------------------------

def _render_docx_modern(resume: Resume) -> bytes:
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)

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
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(10.5)
        # letter spacing approximated via space-after
        return p

    for sec in (resume.section_order or _DEFAULT_ORDER):
        if sec == "summary" and resume.summary:
            section_heading("Summary")
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            p.add_run(resume.summary).font.size = Pt(10.5)
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

def _render_docx_classic(resume: Resume) -> bytes:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    style = doc.styles["Normal"]
    style.font.name = "Georgia"
    style.font.size = Pt(10.8)

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
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(12)
        _set_section_heading_border(p)
        return p

    for sec in (resume.section_order or _DEFAULT_ORDER):
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

def _render_docx_academic(resume: Resume) -> bytes:
    from docx import Document
    from docx.shared import Pt, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    style = doc.styles["Normal"]
    style.font.name = "Georgia"
    style.font.size = Pt(11)

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
        p.paragraph_format.space_before = Pt(16)
        p.paragraph_format.space_after = Pt(5)
        r = p.add_run(text.upper())
        r.bold = True
        r.font.size = Pt(13)
        r.font.name = "Georgia"
        _set_section_heading_border(p, color="111111")
        return p

    for sec in (resume.section_order or _DEFAULT_ORDER):
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
        elif sec == "publications" and resume.publications:
            section_heading("Publications")
            for pub in resume.publications:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.left_indent = Pt(16)
                p.paragraph_format.first_line_indent = Pt(-16)
                r = p.add_run(pub)
                r.font.size = Pt(10.5)
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


def render_docx(resume: Resume, template_id: Optional[str] = "modern") -> bytes:
    builder = _DOCX_BUILDERS.get(_resolve_template_id(template_id), _render_docx_modern)
    return builder(resume)

def resume_to_plaintext(resume: Resume) -> str:
    """Convert Resume object to plaintext representation."""
    lines = [resume.name or ""]
    parts = [v for v in [
        resume.contact.phone, resume.contact.email, resume.contact.location,
        resume.contact.linkedin, resume.contact.github, resume.contact.website,
    ] if v]
    if parts:
        lines.append(" | ".join(parts))

    for sec in (resume.section_order or _DEFAULT_ORDER):
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
