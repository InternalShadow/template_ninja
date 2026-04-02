"""
Blueprint-Driven PDF Generator

Generates a styled resume PDF by applying a TemplateBlueprint to user content.
The blueprint (produced by parsers.template_blueprint) fully determines:
  - Page size
  - Background panels (drawn edge-to-edge on canvas)
  - Frame positions and column widths
  - Per-element-type visual styles (font, size, color, alignment, leading)
  - Section order within each column

No structural or stylistic decisions are hardcoded here — everything comes
from the blueprint.  Backward-compatible: if called with the old theme dict
(has 'header_bg' but not 'background_regions') the legacy renderer is used.
"""
from __future__ import annotations

import copy
import os
from collections import Counter
from functools import partial
from typing import Any

from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Flowable,
    KeepTogether,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INNER_PAD = 8.0          # per-side inner padding inside each frame
_BULLET_CHAR = "\u2022"


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def _rl_color(rgb: list | tuple) -> rl_colors.Color:
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    return rl_colors.Color(r, g, b)


def _is_light(rgb: list | tuple) -> bool:
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    return 0.299 * r + 0.587 * g + 0.114 * b > 0.55


def _contrast(rgb: list | tuple) -> tuple:
    return (0.0, 0.0, 0.0) if _is_light(rgb) else (1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# Font mapping  (template fonts → ReportLab base-14)
# ---------------------------------------------------------------------------

def _safe_font(font_name: str, bold: bool = False, italic: bool = False) -> str:
    """Map any template font name to a ReportLab-embeddable base-14 name."""
    f = (font_name or "").lower()

    # Explicit base-14 passthrough
    _BASE14 = {
        "helvetica", "times-roman", "times", "courier",
        "symbol", "zapfdingbats",
    }
    base_lc = f.split("-")[0].split("+")[-1].strip()
    if base_lc in _BASE14:
        base = base_lc.capitalize()
        if base == "Times":
            base = "Times-Roman"
    elif any(k in f for k in ("times", "georgia", "palatino", "garamond", "baskerville", "book antiqua")):
        base = "Times-Roman"
    elif any(k in f for k in ("courier", "mono", "consolas", "inconsolata", "sourcecodepro")):
        base = "Courier"
    else:
        base = "Helvetica"

    # Detect bold/italic from font name itself
    name_bold = bold or any(k in f for k in ("bold", "heavy", "black", "semibold", "demibold"))
    name_italic = italic or any(k in f for k in ("italic", "oblique", "slant"))

    if base == "Helvetica":
        if name_bold and name_italic:
            return "Helvetica-BoldOblique"
        if name_bold:
            return "Helvetica-Bold"
        if name_italic:
            return "Helvetica-Oblique"
        return "Helvetica"
    elif "Times" in base:
        if name_bold and name_italic:
            return "Times-BoldItalic"
        if name_bold:
            return "Times-Bold"
        if name_italic:
            return "Times-Italic"
        return "Times-Roman"
    elif base == "Courier":
        if name_bold and name_italic:
            return "Courier-BoldOblique"
        if name_bold:
            return "Courier-Bold"
        if name_italic:
            return "Courier-Oblique"
        return "Courier"
    return "Helvetica"


# ---------------------------------------------------------------------------
# ParagraphStyle factory from element_style dict
# ---------------------------------------------------------------------------

def _para_style(
    name: str,
    es: dict,
    *,
    overrides: dict | None = None,
) -> ParagraphStyle:
    """Build a ReportLab ParagraphStyle from an element_style dict."""
    s = dict(es)
    if overrides:
        s.update(overrides)
    font = _safe_font(s.get("font", "Helvetica"), s.get("bold", False), s.get("italic", False))
    color = _rl_color(s.get("color", [0, 0, 0]))
    align = {"left": 0, "center": 1, "right": 2}.get(s.get("align", "left"), 0)
    leading = s.get("leading", s.get("size", 10.0) * 1.35)
    indent = s.get("indent", 0.0)
    return ParagraphStyle(
        name,
        fontName=font,
        fontSize=s.get("size", 10.0),
        leading=leading,
        textColor=color,
        alignment=align,
        spaceBefore=s.get("spacing_before", 0.0),
        spaceAfter=s.get("spacing_after", 2.0),
        leftIndent=indent,
    )


# ---------------------------------------------------------------------------
# Custom Flowables
# ---------------------------------------------------------------------------

class _SectionBar(Flowable):
    """Full-width colored bar with a section title in contrasting text."""

    def __init__(
        self,
        title: str,
        bg_color: list | tuple,
        text_color: list | tuple,
        font_size: float,
        width: float,
        bar_height: float = 16.0,
        padding_left: float = 6.0,
    ) -> None:
        super().__init__()
        self.title = title.upper()
        self.bg_color = bg_color
        self.text_color = text_color
        self.font_size = font_size
        self._width = width
        self.bar_height = bar_height
        self.padding_left = padding_left

    def wrap(self, aw: float, ah: float) -> tuple[float, float]:
        return self._width, self.bar_height

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setFillColor(_rl_color(self.bg_color))
        c.rect(0, 0, self._width, self.bar_height, fill=1, stroke=0)
        c.setFillColor(_rl_color(self.text_color))
        c.setFont("Helvetica-Bold", self.font_size)
        c.drawString(
            self.padding_left,
            (self.bar_height - self.font_size) / 2 + 1,
            self.title,
        )
        c.restoreState()


class _HRule(Flowable):
    """Thin horizontal rule."""

    def __init__(self, width: float, color: list | tuple, thickness: float = 0.5) -> None:
        super().__init__()
        self._width = width
        self.color = color
        self.thickness = thickness

    def wrap(self, aw: float, ah: float) -> tuple[float, float]:
        return self._width, self.thickness + 2

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setStrokeColor(_rl_color(self.color))
        c.setLineWidth(self.thickness)
        c.line(0, self.thickness / 2, self._width, self.thickness / 2)
        c.restoreState()


# ---------------------------------------------------------------------------
# Canvas callback — draw background regions verbatim
# ---------------------------------------------------------------------------

def _draw_backgrounds(canvas, doc, *, blueprint: dict) -> None:
    """
    Draw all background_regions on the raw canvas before content frames.

    PyMuPDF stores coordinates with y=0 at the page TOP (y increases down).
    ReportLab uses y=0 at the page BOTTOM (y increases up).
    Conversion: rl_y0 = page_h - region["y1"]
    """
    ph: float = blueprint["page_height"]
    canvas.saveState()
    for region in blueprint.get("background_regions", []):
        x0 = region["x0"]
        rl_y0 = ph - region["y1"]   # bottom-left in RL coords
        w = region["x1"] - region["x0"]
        h = region["y1"] - region["y0"]
        canvas.setFillColor(_rl_color(region["color"]))
        canvas.rect(x0, rl_y0, w, h, fill=1, stroke=0)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Frame builder
# ---------------------------------------------------------------------------

def _make_frames(columns: list[dict], ph: float) -> list[Frame]:
    """
    Build ReportLab Frame objects from blueprint.columns.

    Column y_top / y_bottom are stored in blueprint as ReportLab coordinates
    (y=0 at bottom).  If they are 0/ph they cover the full page height.
    """
    frames = []
    for col in columns:
        x0 = col["x0"]
        x1 = col["x1"]
        y_bottom = col.get("y_bottom", 0.0)
        y_top = col.get("y_top", ph)
        width = max(x1 - x0, 20.0)
        height = max(y_top - y_bottom, 20.0)
        frames.append(Frame(
            x0, y_bottom, width, height,
            leftPadding=_INNER_PAD,
            rightPadding=_INNER_PAD,
            topPadding=_INNER_PAD,
            bottomPadding=_INNER_PAD,
            id=col.get("id", f"col_{len(frames)}"),
        ))
    return frames


# ---------------------------------------------------------------------------
# Section heading renderer
# ---------------------------------------------------------------------------

def _render_heading(
    heading_text: str,
    es: dict,
    col_w: float,
    section_spacing: float,
) -> list:
    """Render a section heading with bar (if bar_height>0) or bold caps text."""
    heading_es = es.get("section_heading", {})
    bar_h = heading_es.get("bar_height", 0.0)
    bg_color = heading_es.get("bg_color")
    font_size = heading_es.get("size", 10.0)
    text_color = heading_es.get("color", [0, 0, 0])
    spacing_before = heading_es.get("spacing_before", 6.0)
    spacing_after = heading_es.get("spacing_after", 3.0)

    items: list = [Spacer(1, spacing_before)]

    if bar_h > 0 and bg_color:
        text_col = _contrast(bg_color)
        items.append(_SectionBar(
            heading_text, bg_color, text_col,
            font_size, col_w, bar_height=bar_h,
        ))
    else:
        # Plain text heading: bold + caps + rule line
        style = _para_style("_hdg", heading_es, overrides={"bold": True, "align": "left"})
        items.append(Paragraph(heading_text.upper(), style))
        items.append(_HRule(col_w, text_color, thickness=0.75))

    items.append(Spacer(1, spacing_after))
    return items


# ---------------------------------------------------------------------------
# Section content renderers
# ---------------------------------------------------------------------------

def _render_identity(content: dict, es: dict, col_w: float) -> list:
    """Render name + title/subtitle (no section heading)."""
    items: list = []
    name = content.get("name", "").strip()
    title = content.get("title", content.get("subtitle", "")).strip()

    if name and "name" in es:
        items.append(Paragraph(name, _para_style("_name", es["name"])))
    elif name:
        items.append(Paragraph(name, ParagraphStyle(
            "_name_fb", fontName="Helvetica-Bold", fontSize=22, leading=26,
            alignment=1,
        )))

    if title:
        title_es = es.get("subtitle", es.get("name", {}))
        if title_es:
            style = _para_style("_title", title_es, overrides={"bold": False, "size": title_es.get("size", 11)})
            items.append(Paragraph(title, style))
        else:
            items.append(Paragraph(title, ParagraphStyle(
                "_title_fb", fontName="Helvetica", fontSize=11, leading=14,
                alignment=1,
            )))

    items.append(Spacer(1, 4.0))
    return items


def _render_contact(content: dict, es: dict, col_w: float) -> list:
    """Render contact information (one item per line)."""
    contact = content.get("contact", {})
    if not contact:
        return []

    style = _para_style("_contact", es.get("contact_value", es.get("body_paragraph", {
        "font": "Helvetica", "size": 9.5, "color": [0, 0, 0],
        "bold": False, "italic": False, "align": "left", "leading": 13,
    })))

    items: list = []
    for key in ("email", "phone", "location", "linkedin", "github", "website"):
        val = contact.get(key, "").strip()
        if val:
            items.append(Paragraph(val, style))
    return items


def _render_summary(content: dict, es: dict, col_w: float) -> list:
    """Render a summary/profile paragraph."""
    summary = content.get("summary", "").strip()
    if not summary:
        return []
    style = _para_style("_summary", es.get("body_paragraph", es.get("bullet", {
        "font": "Helvetica", "size": 9.5, "color": [0, 0, 0],
        "bold": False, "italic": False, "align": "left", "leading": 13,
    })))
    return [Paragraph(summary, style)]


def _render_experience(
    content: dict,
    es: dict,
    col_w: float,
    job_entry_format: str,
    job_body_format: str,
    entry_spacing: float,
) -> list:
    """Render all experience entries."""
    entries = content.get("experience", [])
    if not entries:
        return []

    # Styles
    company_es = es.get("job_company", es.get("body_paragraph", {}))
    date_es = es.get("job_date", {**company_es, "align": "right"})
    role_es = es.get("job_role", {**company_es, "bold": False, "italic": True})
    bullet_es = es.get("bullet", es.get("body_paragraph", {}))

    company_style = _para_style("_co", company_es)
    date_style = _para_style("_dt", date_es, overrides={"align": "right"})
    role_style = _para_style("_role", role_es)
    bullet_style = _para_style("_bul", bullet_es, overrides={"leftIndent": 10})
    para_style = _para_style("_para", es.get("body_paragraph", bullet_es))

    items: list = []
    for entry in entries:
        company = entry.get("company", "").strip()
        dates = entry.get("dates", "").strip()
        role = entry.get("role", "").strip()
        location = entry.get("location", "").strip()
        bullets = [b.strip() for b in entry.get("bullets", []) if b.strip()]
        description = entry.get("description", entry.get("summary", "")).strip()

        block: list = []

        # Company + date row
        if company or dates:
            comp_para = Paragraph(company or "", company_style)
            date_para = Paragraph(dates or "", date_style)
            row = Table(
                [[comp_para, date_para]],
                colWidths=[col_w * 0.62, col_w * 0.38],
            )
            row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
            ]))
            block.append(row)

        if role:
            block.append(Paragraph(role, role_style))
        if location and location not in (company, role):
            block.append(Paragraph(location, para_style))

        # Body: bullets or paragraph
        if job_body_format == "paragraph" and description:
            block.append(Paragraph(description, para_style))
        elif bullets:
            for b in bullets:
                char = bullet_es.get("bullet_char", _BULLET_CHAR) or _BULLET_CHAR
                block.append(Paragraph(f"{char}  {b}", bullet_style))
        elif description:
            block.append(Paragraph(description, para_style))

        block.append(Spacer(1, entry_spacing))
        items.append(KeepTogether(block))

    return items


def _render_skills(
    content: dict,
    es: dict,
    col_w: float,
    skill_format: str,
) -> list:
    """Render skills in the format detected from the template."""
    skills = content.get("skills", [])
    if not skills:
        return []

    cat_es = es.get("skill_category", es.get("body_paragraph", {}))
    item_es = es.get("skill_item", es.get("body_paragraph", {}))
    inline_es = es.get("skill_inline", cat_es)

    cat_style = _para_style("_scat", cat_es, overrides={"bold": True})
    item_style = _para_style("_sitem", item_es, overrides={"bold": False})
    inline_style = _para_style("_sinline", inline_es)

    items: list = []

    for skill in skills:
        cat = skill.get("category", "").strip()
        items_raw = skill.get("items", "").strip()

        if skill_format == "flat":
            # Each item as its own line (or comma-joined)
            for piece in (items_raw.split(",") if items_raw else [cat]):
                piece = piece.strip()
                if piece:
                    items.append(Paragraph(piece, item_style))

        elif skill_format == "heading_items":
            if cat:
                items.append(Paragraph(cat, cat_style))
            for piece in (items_raw.split(",") if items_raw else []):
                piece = piece.strip()
                if piece:
                    items.append(Paragraph(piece, item_style))

        else:  # inline (default)
            if cat and items_raw:
                text = f"<b>{cat}:</b> {items_raw}"
            elif cat:
                text = f"<b>{cat}</b>"
            else:
                text = items_raw
            if text:
                items.append(Paragraph(text, inline_style))

    return items


def _render_education(content: dict, es: dict, col_w: float) -> list:
    """Render education entries."""
    education = content.get("education", [])
    if not education:
        return []

    school_es = es.get("edu_school", es.get("job_company", es.get("body_paragraph", {})))
    degree_es = es.get("edu_degree", es.get("body_paragraph", {}))
    dates_es = es.get("edu_dates", {**degree_es, "align": "right"})

    school_style = _para_style("_school", school_es, overrides={"bold": True})
    degree_style = _para_style("_degree", degree_es)
    dates_style = _para_style("_edates", dates_es, overrides={"align": "right"})

    items: list = []
    for edu in education:
        degree = edu.get("degree", "").strip()
        school = edu.get("school", "").strip()
        dates = edu.get("dates", "").strip()

        block: list = []
        if school and dates:
            school_para = Paragraph(school, school_style)
            dates_para = Paragraph(dates, dates_style)
            row = Table([[school_para, dates_para]], colWidths=[col_w * 0.62, col_w * 0.38])
            row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
            ]))
            block.append(row)
        elif school:
            block.append(Paragraph(school, school_style))
            if dates:
                block.append(Paragraph(dates, dates_style))

        if degree:
            block.append(Paragraph(degree, degree_style))

        block.append(Spacer(1, 4.0))
        items.extend(block)

    return items


def _render_projects(content: dict, es: dict, col_w: float) -> list:
    """Render project entries (same structure as experience)."""
    projects = content.get("projects", [])
    if not projects:
        return []

    company_es = es.get("job_company", es.get("body_paragraph", {}))
    bullet_es = es.get("bullet", es.get("body_paragraph", {}))
    company_style = _para_style("_pco", company_es, overrides={"bold": True})
    role_style = _para_style("_prole", es.get("job_role", company_es))
    bullet_style = _para_style("_pbul", bullet_es, overrides={"leftIndent": 10})
    para_style = _para_style("_ppara", es.get("body_paragraph", bullet_es))

    items: list = []
    for proj in projects:
        name = proj.get("name", proj.get("company", "")).strip()
        role = proj.get("role", proj.get("subtitle", "")).strip()
        dates = proj.get("dates", "").strip()
        bullets = [b.strip() for b in proj.get("bullets", []) if b.strip()]
        description = proj.get("description", "").strip()

        block: list = []
        if name:
            block.append(Paragraph(name, company_style))
        if role:
            block.append(Paragraph(role, role_style))
        if dates:
            block.append(Paragraph(dates, para_style))
        for b in bullets:
            char = bullet_es.get("bullet_char", _BULLET_CHAR) or _BULLET_CHAR
            block.append(Paragraph(f"{char}  {b}", bullet_style))
        if description and not bullets:
            block.append(Paragraph(description, para_style))
        block.append(Spacer(1, 4.0))
        items.extend(block)
    return items


def _render_generic(section_type: str, content: dict, es: dict) -> list:
    """Fallback renderer for unknown section types."""
    data = content.get(section_type, content.get(section_type.rstrip("s"), []))
    if not data:
        return []

    style = _para_style("_gen", es.get("body_paragraph", {
        "font": "Helvetica", "size": 9.5, "color": [0, 0, 0],
        "bold": False, "italic": False, "align": "left", "leading": 13,
    }))

    if isinstance(data, str):
        return [Paragraph(data, style)]
    if isinstance(data, list):
        items = []
        for item in data:
            text = item if isinstance(item, str) else (item.get("text", str(item)))
            if text:
                items.append(Paragraph(text.strip(), style))
        return items
    return []


# Dispatch table: section_type → renderer
_SECTION_RENDERERS: dict[str, Any] = {
    "identity": None,       # handled specially
    "contact": _render_contact,
    "summary": _render_summary,
    "experience": None,     # needs extra args
    "expertise": None,      # same as experience
    "skills": None,         # needs skill_format
    "education": _render_education,
    "projects": _render_projects,
    "certifications": _render_generic,
    "awards": _render_generic,
    "publications": _render_generic,
    "volunteer": _render_generic,
    "languages": _render_generic,
    "interests": _render_generic,
}


# ---------------------------------------------------------------------------
# Story assembly
# ---------------------------------------------------------------------------

def _assemble_story(blueprint: dict, content: dict) -> list:
    """Build the complete ReportLab story from blueprint and content."""
    es = blueprint.get("element_styles", {})
    section_map = blueprint.get("section_map", {})
    columns = blueprint.get("columns", [])
    skill_fmt = blueprint.get("skill_format", "inline")
    job_fmt = blueprint.get("job_entry_format", "two_line")
    job_body_fmt = blueprint.get("job_body_format", "bullet")
    section_spacing = blueprint.get("section_spacing", 6.0)
    entry_spacing = blueprint.get("entry_spacing", 4.0)

    story: list = []
    rendered_types: set[str] = set()

    for col_idx, col in enumerate(columns):
        col_key = f"col_{col_idx}"
        sections = section_map.get(col_key, [])
        col_w = (col["x1"] - col["x0"]) - 2 * _INNER_PAD

        for section in sections:
            sec_type = section.get("type", "")
            heading_text = section.get("heading_text", "")

            # Allow user-supplied label overrides
            label_key = f"{sec_type}_label"
            if label_key in content:
                heading_text = content[label_key]

            if sec_type == "identity":
                story.extend(_render_identity(content, es, col_w))
                rendered_types.add("identity")

            elif sec_type.startswith("custom_"):
                # Unrecognized sections: render as generic text if data present
                story.extend(_render_heading(heading_text or sec_type, es, col_w, section_spacing))
                story.extend(_render_generic(sec_type, content, es))
                rendered_types.add(sec_type)

            elif sec_type in ("experience", "expertise"):
                if content.get("experience"):
                    story.extend(_render_heading(heading_text or "EXPERIENCE", es, col_w, section_spacing))
                    story.extend(_render_experience(
                        content, es, col_w, job_fmt, job_body_fmt, entry_spacing
                    ))
                rendered_types.add("experience")

            elif sec_type == "skills":
                if content.get("skills"):
                    story.extend(_render_heading(heading_text or "SKILLS", es, col_w, section_spacing))
                    story.extend(_render_skills(content, es, col_w, skill_fmt))
                rendered_types.add("skills")

            elif sec_type in _SECTION_RENDERERS and _SECTION_RENDERERS[sec_type] is not None:
                renderer = _SECTION_RENDERERS[sec_type]
                section_content = renderer(content, es, col_w)
                if section_content:
                    story.extend(_render_heading(heading_text or sec_type.upper(), es, col_w, section_spacing))
                    story.extend(section_content)
                rendered_types.add(sec_type)

            else:
                # Try generic fallback
                generic = _render_generic(sec_type, content, es)
                if generic:
                    story.extend(_render_heading(heading_text or sec_type.upper(), es, col_w, section_spacing))
                    story.extend(generic)
                rendered_types.add(sec_type)

        # FrameBreak between columns
        if col_idx < len(columns) - 1:
            story.append(FrameBreak())

    # ── Render any content sections not covered by section_map ────────────
    # Prevents data from being silently dropped when section_map is incomplete
    fallback_types = [
        ("summary", "SUMMARY", _render_summary),
        ("experience", "EXPERIENCE", None),
        ("skills", "SKILLS", None),
        ("education", "EDUCATION", _render_education),
        ("projects", "PROJECTS", _render_projects),
    ]
    last_col = columns[-1] if columns else {"x0": 28, "x1": 584}
    fallback_col_w = (last_col["x1"] - last_col["x0"]) - 2 * _INNER_PAD

    for ft, default_heading, renderer in fallback_types:
        if ft not in rendered_types:
            if ft == "experience" and content.get("experience"):
                story.extend(_render_heading(default_heading, es, fallback_col_w, section_spacing))
                story.extend(_render_experience(content, es, fallback_col_w, job_fmt, job_body_fmt, entry_spacing))
            elif ft == "skills" and content.get("skills"):
                story.extend(_render_heading(default_heading, es, fallback_col_w, section_spacing))
                story.extend(_render_skills(content, es, fallback_col_w, skill_fmt))
            elif renderer and content.get(ft):
                result = renderer(content, es, fallback_col_w)
                if result:
                    story.extend(_render_heading(default_heading, es, fallback_col_w, section_spacing))
                    story.extend(result)

    return story


# ---------------------------------------------------------------------------
# Legacy theme → minimal blueprint converter (backward compatibility)
# ---------------------------------------------------------------------------

def _theme_to_blueprint(theme: dict) -> dict:
    """Convert the old thin-theme dict to a minimal blueprint dict."""
    pw = float(theme.get("page_width", 612.0))
    ph = float(theme.get("page_height", 792.0))
    layout = theme.get("layout_type", "single_column")
    sidebar_w = float(theme.get("sidebar_width", 0.0))
    sidebar_side = theme.get("sidebar_side")
    header_h = float(theme.get("header_height", 0.0))
    sidebar_color = theme.get("sidebar_color", [0.2, 0.2, 0.2])
    section_bg = theme.get("section_bg", [0.3, 0.3, 0.3])
    header_bg = theme.get("header_bg", [0.2, 0.2, 0.2])
    body_size = float(theme.get("body_font_size", 9.5))
    heading_size = float(theme.get("heading_font_size", 10.5))
    name_size = float(theme.get("name_font_size", 22.0))
    header_tc = theme.get("header_text_color", [1.0, 1.0, 1.0])
    body_tc = theme.get("body_text_color", [0.0, 0.0, 0.0])
    sidebar_tc = list(_contrast(sidebar_color))
    sec_tc = list(_contrast(section_bg))
    lm = float(theme.get("left_margin", 28.0))
    rm = float(theme.get("right_margin", 28.0))
    bm = float(theme.get("bottom_margin", 28.0))
    bar_h = float(theme.get("section_bar_height", 16.0))
    line_sp = float(theme.get("line_spacing", body_size * 1.4))

    # Build background_regions
    bg_regions: list[dict] = []
    if layout in ("left_sidebar", "right_sidebar") and sidebar_w > 0:
        if sidebar_side == "left":
            bg_regions.append({"x0": 0, "y0": 0, "x1": sidebar_w, "y1": ph,
                                "width": sidebar_w, "height": ph, "color": list(sidebar_color)})
        else:
            bg_regions.append({"x0": pw - sidebar_w, "y0": 0, "x1": pw, "y1": ph,
                                "width": sidebar_w, "height": ph, "color": list(sidebar_color)})
    if header_h > 0:
        bg_regions.append({"x0": 0, "y0": 0, "x1": pw, "y1": header_h,
                            "width": pw, "height": header_h, "color": list(header_bg)})

    # Build columns
    if layout == "left_sidebar" and sidebar_w > 0:
        columns = [
            {"id": "col_0", "x0": 0, "x1": sidebar_w, "y_top": ph, "y_bottom": bm},
            {"id": "col_1", "x0": sidebar_w, "x1": pw, "y_top": ph, "y_bottom": bm},
        ]
        name_col = 1
        section_map = {
            "col_0": [
                {"type": "contact", "heading_text": "CONTACT"},
                {"type": "skills", "heading_text": "SKILLS"},
                {"type": "education", "heading_text": "EDUCATION"},
            ],
            "col_1": [
                {"type": "identity"},
                {"type": "summary", "heading_text": "SUMMARY"},
                {"type": "experience", "heading_text": "EXPERIENCE"},
            ],
        }
    elif layout == "right_sidebar" and sidebar_w > 0:
        columns = [
            {"id": "col_0", "x0": 0, "x1": pw - sidebar_w, "y_top": ph, "y_bottom": bm},
            {"id": "col_1", "x0": pw - sidebar_w, "x1": pw, "y_top": ph, "y_bottom": bm},
        ]
        name_col = 0
        section_map = {
            "col_0": [
                {"type": "identity"},
                {"type": "summary", "heading_text": "SUMMARY"},
                {"type": "experience", "heading_text": "EXPERIENCE"},
            ],
            "col_1": [
                {"type": "contact", "heading_text": "CONTACT"},
                {"type": "skills", "heading_text": "SKILLS"},
                {"type": "education", "heading_text": "EDUCATION"},
            ],
        }
    else:
        columns = [{"id": "col_0", "x0": lm, "x1": pw - rm, "y_top": ph, "y_bottom": bm}]
        name_col = 0
        section_map = {
            "col_0": [
                {"type": "identity"},
                {"type": "contact", "heading_text": "CONTACT"},
                {"type": "summary", "heading_text": "PROFESSIONAL SUMMARY"},
                {"type": "skills", "heading_text": "SKILLS"},
                {"type": "experience", "heading_text": "EXPERIENCE"},
                {"type": "education", "heading_text": "EDUCATION"},
            ],
        }

    is_dark_header = not _is_light(header_bg if header_h > 0 else [0.15, 0.15, 0.15])
    name_color = list(header_tc) if is_dark_header else [0.0, 0.0, 0.0]
    if layout in ("left_sidebar", "right_sidebar"):
        name_color = sidebar_tc

    element_styles = {
        "name": {
            "font": "Helvetica-Bold", "size": name_size,
            "color": name_color, "bold": True, "italic": False,
            "align": "center", "leading": name_size * 1.2,
            "spacing_before": 0, "spacing_after": 2,
            "bar_height": 0, "bg_color": None, "col_idx": name_col,
        },
        "subtitle": {
            "font": "Helvetica", "size": body_size + 2,
            "color": name_color, "bold": False, "italic": False,
            "align": "center", "leading": (body_size + 2) * 1.3,
            "spacing_before": 0, "spacing_after": 2,
            "bar_height": 0, "bg_color": None, "col_idx": name_col,
        },
        "section_heading": {
            "font": "Helvetica-Bold", "size": heading_size,
            "color": list(sec_tc), "bold": True, "italic": False,
            "align": "left", "leading": heading_size * 1.3,
            "bg_color": list(section_bg), "bar_height": bar_h,
            "spacing_before": 6, "spacing_after": 3,
            "col_idx": 0,
        },
        "contact_value": {
            "font": "Helvetica", "size": body_size,
            "color": sidebar_tc if layout != "single_column" else list(body_tc),
            "bold": False, "italic": False,
            "align": "left", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": 0,
        },
        "job_company": {
            "font": "Helvetica-Bold", "size": body_size,
            "color": list(body_tc), "bold": True, "italic": False,
            "align": "left", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": name_col,
        },
        "job_date": {
            "font": "Helvetica", "size": body_size,
            "color": [0.4, 0.4, 0.4], "bold": False, "italic": False,
            "align": "right", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": name_col,
        },
        "job_role": {
            "font": "Helvetica-Oblique", "size": body_size,
            "color": list(body_tc), "bold": False, "italic": True,
            "align": "left", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": name_col,
        },
        "bullet": {
            "font": "Helvetica", "size": body_size,
            "color": list(body_tc), "bold": False, "italic": False,
            "align": "left", "leading": line_sp, "indent": 10,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "bullet_char": _BULLET_CHAR,
            "col_idx": name_col,
        },
        "skill_category": {
            "font": "Helvetica-Bold", "size": body_size,
            "color": sidebar_tc if layout != "single_column" else list(body_tc),
            "bold": True, "italic": False,
            "align": "left", "leading": line_sp,
            "spacing_before": 2, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": 0,
        },
        "skill_item": {
            "font": "Helvetica", "size": body_size,
            "color": sidebar_tc if layout != "single_column" else list(body_tc),
            "bold": False, "italic": False,
            "align": "left", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": 0,
        },
        "edu_school": {
            "font": "Helvetica-Bold", "size": body_size,
            "color": list(body_tc), "bold": True, "italic": False,
            "align": "left", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": 0,
        },
        "edu_degree": {
            "font": "Helvetica", "size": body_size,
            "color": list(body_tc), "bold": False, "italic": False,
            "align": "left", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": 0,
        },
        "edu_dates": {
            "font": "Helvetica", "size": body_size,
            "color": [0.4, 0.4, 0.4], "bold": False, "italic": False,
            "align": "right", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 1,
            "bar_height": 0, "bg_color": None, "col_idx": 0,
        },
        "body_paragraph": {
            "font": "Helvetica", "size": body_size,
            "color": list(body_tc), "bold": False, "italic": False,
            "align": "left", "leading": line_sp,
            "spacing_before": 0, "spacing_after": 2,
            "bar_height": 0, "bg_color": None, "col_idx": 0,
        },
    }

    return {
        "page_width": pw,
        "page_height": ph,
        "layout_type": layout,
        "background_regions": bg_regions,
        "columns": columns,
        "element_styles": element_styles,
        "section_map": section_map,
        "name_col_idx": name_col,
        "skill_format": "inline",
        "job_entry_format": "two_line",
        "job_body_format": "bullet",
        "line_spacing": line_sp,
        "section_spacing": float(theme.get("section_spacing", 6.0)),
        "entry_spacing": 4.0,
        "bullet_indent": 10.0,
    }


# ---------------------------------------------------------------------------
# Layout auto-correction (safety net for mis-detected column layouts)
# ---------------------------------------------------------------------------

def _auto_correct_layout(blueprint: dict) -> dict:
    """
    Detect and fix the case where all sections landed in a narrow column.

    This happens when column detection produces a two-column blueprint
    (e.g. false "left_sidebar") but every section ends up in col_0 while col_1
    is empty AND col_0 is narrower than 35 % of the page width.  Rendering all
    content into a ~90 pt frame produces unreadable output, so we collapse to
    a sensible single-column layout instead.
    """
    columns = blueprint.get("columns", [])
    section_map = blueprint.get("section_map", {})
    if len(columns) != 2:
        return blueprint

    col0_secs = section_map.get("col_0", [])
    col1_secs = section_map.get("col_1", [])
    pw = float(blueprint.get("page_width", 612))
    ph = float(blueprint.get("page_height", 792))
    col0_w = columns[0]["x1"] - columns[0]["x0"]
    col1_w = columns[1]["x1"] - columns[1]["x0"]
    margin = 28.0

    def _collapse(all_secs: list[dict]) -> dict:
        bp = copy.deepcopy(blueprint)
        bp["layout_type"] = "single_column"
        bp["columns"] = [{"id": "col_0", "x0": margin, "x1": pw - margin,
                          "y_top": ph, "y_bottom": margin}]
        bp["section_map"] = {"col_0": all_secs, "col_1": []}
        return bp

    # All sections in narrow col_0, col_1 is empty
    if col0_secs and not col1_secs and col0_w < pw * 0.35:
        return _collapse(col0_secs)

    # All sections in narrow col_1, col_0 is empty (right_sidebar edge case)
    if col1_secs and not col0_secs and col1_w < pw * 0.35:
        return _collapse(col1_secs)

    # Identity-in-narrow-sidebar safety net:
    # For sidebar layouts, if the identity section is in the narrow sidebar
    # column AND a full-width background region exists (indicating a header
    # band that spans both columns), move identity to the main column.
    # This handles templates like Denny Cheng where the name lives inside a
    # full-width dark header, not inside the sidebar itself.
    layout_type = blueprint.get("layout_type", "single_column")
    bg_regions  = blueprint.get("background_regions", [])

    if layout_type in ("left_sidebar", "right_sidebar"):
        sidebar_key  = "col_0" if layout_type == "left_sidebar" else "col_1"
        main_key     = "col_1" if layout_type == "left_sidebar" else "col_0"
        sidebar_secs = section_map.get(sidebar_key, [])
        main_secs    = section_map.get(main_key, [])
        sidebar_col  = columns[0] if layout_type == "left_sidebar" else columns[1]
        sidebar_w    = sidebar_col["x1"] - sidebar_col["x0"]

        has_identity_in_sidebar = any(s.get("type") == "identity" for s in sidebar_secs)
        has_full_width_bg       = any(r["width"] > pw * 0.75 for r in bg_regions)

        if has_identity_in_sidebar and has_full_width_bg and sidebar_w < pw * 0.40:
            bp = copy.deepcopy(blueprint)
            identity_secs  = [s for s in sidebar_secs if s.get("type") == "identity"]
            remaining_side = [s for s in sidebar_secs if s.get("type") != "identity"]
            bp["section_map"][sidebar_key] = remaining_side
            bp["section_map"][main_key]    = identity_secs + [
                s for s in main_secs if s.get("type") != "identity"
            ]
            return bp

    return blueprint


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class PdfBuilder:
    """Generate a resume PDF from a TemplateBlueprint and user content."""

    def build(
        self,
        blueprint_or_theme: dict[str, Any],
        content: dict[str, Any],
        output_path: str,
    ) -> str:
        """
        Generate the PDF at *output_path* and return the path.

        Parameters
        ----------
        blueprint_or_theme:
            A TemplateBlueprint dict (from ``parsers.template_blueprint``) OR
            the legacy thin-theme dict (from ``parsers.template_analyzer``).
            If the dict has a ``background_regions`` key it is treated as a
            blueprint; otherwise it is converted via ``_theme_to_blueprint``.
        content:
            Structured resume content dict:
            {
                "name": str, "title": str, "subtitle": str,
                "summary": str,
                "contact": {"email", "phone", "location", "linkedin", "github"},
                "skills":  [{"category": str, "items": str}],
                "experience": [{"company", "role", "dates", "location",
                                "bullets": [str], "description": str}],
                "education": [{"degree", "school", "dates"}],
                "projects":  [{"name", "role", "dates", "bullets", "description"}],
            }
        output_path:
            Destination file path for the generated PDF.
        """
        os.makedirs(
            os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
            exist_ok=True,
        )

        # Detect blueprint vs. legacy theme
        if "background_regions" in blueprint_or_theme:
            blueprint = blueprint_or_theme
        else:
            blueprint = _theme_to_blueprint(blueprint_or_theme)

        # Safety net: if all sections are in a narrow column and the other is
        # empty, collapse to single-column to avoid crammed unreadable output.
        blueprint = _auto_correct_layout(blueprint)

        pw = float(blueprint["page_width"])
        ph = float(blueprint["page_height"])

        # Build frames
        frames = _make_frames(blueprint["columns"], ph)
        if not frames:
            frames = [Frame(0, 0, pw, ph, id="main")]

        # Assemble story
        story = _assemble_story(blueprint, content)

        # Create document (zero document margins — frames are positioned absolutely)
        doc = BaseDocTemplate(
            output_path,
            pagesize=(pw, ph),
            leftMargin=0,
            rightMargin=0,
            topMargin=0,
            bottomMargin=0,
        )
        bg_fn = partial(_draw_backgrounds, blueprint=blueprint)
        doc.addPageTemplates([
            PageTemplate(id="main", frames=frames, onPage=bg_fn)
        ])
        doc.build(story)
        return output_path
