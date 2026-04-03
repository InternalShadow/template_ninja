"""Unified PyMuPDF extraction pipeline.

Takes a PDF path and returns a validated Blueprint model by:
1. Extracting background regions from page drawings
2. Extracting text spans with font/style metadata
3. Detecting column layout via text-density histogram
4. Classifying text styles into semantic roles
5. Detecting section headings and building a section map
6. Computing spacing metrics and format heuristics
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import fitz
import structlog

from app.models.blueprint import (
    BackgroundRegion,
    Blueprint,
    Column,
    ElementStyle,
    Section,
)

logger = structlog.stdlib.get_logger()

_MIN_BG_AREA = 200.0
_MIN_BG_DIMENSION = 5.0
_MIN_COLUMN_GAP_PT = 15.0
_HEADER_FRACTION = 0.15
_BULLET_CHARS = frozenset("•·–—-▪▸►◦‣⁃")
_MAX_DRAWN_BULLET_SIZE = 6.0

_SECTION_KEYWORDS: dict[str, str] = {
    "experience": "experience",
    "work experience": "experience",
    "employment": "experience",
    "professional experience": "experience",
    "education": "education",
    "academic background": "education",
    "skills": "skills",
    "technical skills": "skills",
    "skills & expertise": "skills",
    "core competencies": "skills",
    "projects": "projects",
    "personal projects": "projects",
    "summary": "summary",
    "objective": "summary",
    "profile": "summary",
    "professional summary": "summary",
    "certifications": "certifications",
    "certificates": "certifications",
    "licenses": "certifications",
    "awards": "awards",
    "honors": "awards",
    "achievements": "awards",
    "contact": "contact",
    "contact information": "contact",
    "publications": "publications",
    "research": "publications",
    "volunteer": "volunteer",
    "volunteering": "volunteer",
    "community involvement": "volunteer",
    "interests": "interests",
    "hobbies": "interests",
    "references": "references",
    "languages": "languages",
}


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _Span:
    """Single text span with positional and style metadata."""

    text: str
    font: str
    size: float
    color: tuple[float, float, float]
    bold: bool
    italic: bool
    x0: float
    y0: float
    x1: float
    y1: float
    col_idx: int = 0


@dataclass
class _StyleGroup:
    """Spans sharing identical visual properties."""

    font: str
    size: float
    color: tuple[float, float, float]
    bold: bool
    italic: bool
    spans: list[_Span] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(s.text) for s in self.spans)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_blueprint(pdf_path: Path) -> Blueprint:
    """Extract a complete visual blueprint from a template PDF.

    Parameters
    ----------
    pdf_path : Path
        Path to the source PDF file.

    Returns
    -------
    Blueprint
        Validated blueprint model ready for storage or generation.

    Raises
    ------
    FileNotFoundError
        If *pdf_path* does not exist.
    ValueError
        If the PDF cannot be opened or has no pages.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info("extraction_started", pdf_path=str(pdf_path))
    with fitz.open(str(pdf_path)) as doc:
        if doc.page_count == 0:
            raise ValueError(f"PDF has no pages: {pdf_path}")

        page = doc[0]
        pw = page.rect.width
        ph = page.rect.height

        bg_regions = _extract_background_regions(page)
        spans = _extract_text_spans(page)

        if not spans:
            logger.warning("no_text_found", pdf_path=str(pdf_path))
            return Blueprint(
                page_width=pw,
                page_height=ph,
                columns=[Column(id="col_0", x0=0.0, x1=pw, y_top=ph, y_bottom=0.0)],
            )

        body_spans = [s for s in spans if s.y0 > ph * _HEADER_FRACTION]
        if len(body_spans) >= 4:
            columns = _detect_columns(pw, ph, body_spans)
        else:
            columns = _detect_columns(pw, ph, spans)
        _assign_columns(spans, columns)

        style_groups = _group_by_style(spans)
        element_styles = _classify_roles(style_groups, columns, pw, ph)

        section_map = _detect_sections(spans, columns, element_styles)
        drawn_bullets = _find_drawn_bullets(page)
        spacing = _compute_spacing(spans, element_styles, ph, drawn_bullets)
        formats = _detect_formats(spans, drawn_bullets, element_styles)

    layout_type = "two_column" if len(columns) >= 2 else "single_column"

    blueprint = Blueprint(
        page_width=pw,
        page_height=ph,
        layout_type=layout_type,
        background_regions=bg_regions,
        columns=columns,
        element_styles=element_styles,
        section_map=section_map,
        **spacing,
        **formats,
    )

    logger.info(
        "extraction_complete",
        pdf_path=str(pdf_path),
        layout=layout_type,
        columns=len(columns),
        styles=len(element_styles),
        sections=sum(len(v) for v in section_map.values()),
        bg_regions=len(bg_regions),
    )
    return blueprint


# ---------------------------------------------------------------------------
# Step 1 – Background regions from page drawings
# ---------------------------------------------------------------------------


def _extract_background_regions(page: fitz.Page) -> list[BackgroundRegion]:
    """Extract filled rectangles from page vector drawings."""
    regions: list[BackgroundRegion] = []

    for path in page.get_drawings():
        fill = path.get("fill")
        if fill is None:
            continue

        rect = path.get("rect")
        if rect is None:
            continue

        w, h = abs(rect.width), abs(rect.height)
        if w * h < _MIN_BG_AREA or w < _MIN_BG_DIMENSION or h < _MIN_BG_DIMENSION:
            continue

        color = _normalize_drawing_color(fill)
        if color is None or all(c > 0.98 for c in color):
            continue

        regions.append(
            BackgroundRegion(
                x0=float(rect.x0),
                y0=float(rect.y0),
                x1=float(rect.x1),
                y1=float(rect.y1),
                color=color,
                opacity=float(path.get("fill_opacity", 1.0)),
            )
        )

    logger.debug("bg_regions_extracted", count=len(regions))
    return regions


# ---------------------------------------------------------------------------
# Step 2 – Text span extraction
# ---------------------------------------------------------------------------


def _extract_text_spans(page: fitz.Page) -> list[_Span]:
    """Pull every text span with font, size, colour, and bounding box."""
    spans: list[_Span] = []
    text_dict = page.get_text("dict")

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for sp in line.get("spans", []):
                text = sp.get("text", "").strip()
                if not text:
                    continue

                color = _srgb_int_to_floats(sp.get("color", 0))
                flags = sp.get("flags", 0)
                font_raw = sp.get("font", "")

                bold = bool(flags & 16) or _font_name_indicates(
                    font_raw, ("bold", "black", "heavy")
                )
                italic = bool(flags & 2) or _font_name_indicates(
                    font_raw, ("italic", "oblique")
                )

                bbox = sp.get("bbox", (0, 0, 0, 0))
                spans.append(
                    _Span(
                        text=text,
                        font=_clean_font_name(font_raw),
                        size=round(sp.get("size", 0.0), 2),
                        color=color,
                        bold=bold,
                        italic=italic,
                        x0=float(bbox[0]),
                        y0=float(bbox[1]),
                        x1=float(bbox[2]),
                        y1=float(bbox[3]),
                    )
                )

    logger.debug("text_spans_extracted", count=len(spans))
    return spans


# ---------------------------------------------------------------------------
# Step 3 – Column detection
# ---------------------------------------------------------------------------


def _detect_columns(
    page_width: float,
    page_height: float,
    spans: list[_Span],
) -> list[Column]:
    """Detect vertical column regions via a text-density histogram."""
    n_bins = max(int(page_width), 100)
    bin_w = page_width / n_bins
    density = [0] * n_bins

    for s in spans:
        lo = max(0, int(s.x0 / bin_w))
        hi = min(n_bins - 1, int(s.x1 / bin_w))
        for b in range(lo, hi + 1):
            density[b] += 1

    margin = page_width * 0.05
    gaps: list[tuple[float, float]] = []
    i = 0
    while i < n_bins:
        if density[i] == 0:
            start = i
            while i < n_bins and density[i] == 0:
                i += 1
            gap_x0 = start * bin_w
            gap_x1 = i * bin_w
            if gap_x0 > margin and gap_x1 < (page_width - margin):
                if (gap_x1 - gap_x0) >= _MIN_COLUMN_GAP_PT:
                    gaps.append((gap_x0, gap_x1))
        else:
            i += 1

    if not gaps:
        return [_single_column(spans, page_width, page_height)]

    gap = max(gaps, key=lambda g: g[1] - g[0])
    mid = (gap[0] + gap[1]) / 2

    left = [s for s in spans if (s.x0 + s.x1) / 2 < mid]
    right = [s for s in spans if (s.x0 + s.x1) / 2 >= mid]

    cols: list[Column] = []
    if left:
        cols.append(
            Column(
                id="col_0",
                x0=min(s.x0 for s in left),
                x1=gap[0],
                y_top=page_height,
                y_bottom=0,
            )
        )
    if right:
        cols.append(
            Column(
                id=f"col_{len(cols)}",
                x0=gap[1],
                x1=max(s.x1 for s in right),
                y_top=page_height,
                y_bottom=0,
            )
        )

    return cols or [_single_column(spans, page_width, page_height)]


def _single_column(
    spans: list[_Span],
    page_width: float,
    page_height: float,
) -> Column:
    return Column(
        id="col_0",
        x0=min(s.x0 for s in spans) if spans else 0,
        x1=max(s.x1 for s in spans) if spans else page_width,
        y_top=page_height,
        y_bottom=0,
    )


def _assign_columns(spans: list[_Span], columns: list[Column]) -> None:
    """Tag each span with its column index.

    Uses x0-containment first (which column's x-range contains the span's
    left edge), then falls back to nearest-centre for spans that fall
    outside all column ranges (e.g. header text).
    """
    centres = [(col.x0 + col.x1) / 2 for col in columns]
    for span in spans:
        assigned = False
        for i, col in enumerate(columns):
            if col.x0 - 5 <= span.x0 <= col.x1 + 5:
                span.col_idx = i
                assigned = True
                break
        if not assigned:
            sc = (span.x0 + span.x1) / 2
            span.col_idx = min(range(len(centres)), key=lambda idx: abs(sc - centres[idx]))


# ---------------------------------------------------------------------------
# Step 4 – Style grouping and role classification
# ---------------------------------------------------------------------------


def _group_by_style(spans: list[_Span]) -> list[_StyleGroup]:
    """Cluster spans with matching (font, rounded size, bold, italic)."""
    groups: dict[tuple, _StyleGroup] = {}
    for s in spans:
        key = (s.font, round(s.size, 1), s.bold, s.italic)
        if key not in groups:
            groups[key] = _StyleGroup(
                font=s.font,
                size=s.size,
                color=s.color,
                bold=s.bold,
                italic=s.italic,
            )
        groups[key].spans.append(s)

    return sorted(groups.values(), key=lambda g: (-g.size, -g.char_count))


def _classify_roles(
    groups: list[_StyleGroup],
    columns: list[Column],
    page_width: float,
    page_height: float,
) -> dict[str, ElementStyle]:
    """Heuristic assignment of semantic roles to style groups.

    Roles assigned (when detected): name, title, section_heading,
    body_paragraph, contact, body_bold, body_italic, detail.
    """
    if not groups:
        return {}

    all_spans = [s for g in groups for s in g.spans]
    body_group = max(groups, key=lambda g: g.char_count)
    body_size = body_group.size

    roles: dict[str, ElementStyle] = {}
    used: set[int] = set()

    def _style(g: _StyleGroup) -> ElementStyle:
        return _to_element_style(g, columns, all_spans)

    # -- name: largest size, near page top --
    for i, g in enumerate(groups):
        if g.size <= body_size:
            break
        if any(s.y0 < page_height * 0.25 for s in g.spans):
            roles["name"] = _style(g)
            used.add(i)
            break

    # -- title: second-largest near top, smaller than name --
    name_size = roles["name"].size if "name" in roles else float("inf")
    for i, g in enumerate(groups):
        if i in used or g.size <= body_size or g.size >= name_size:
            continue
        if any(s.y0 < page_height * 0.25 for s in g.spans):
            roles["title"] = _style(g)
            used.add(i)
            break

    # -- section_heading: bold / all-caps, matching keywords or repeated --
    for i, g in enumerate(groups):
        if i in used:
            continue
        texts = {s.text.strip().lower() for s in g.spans}
        is_keyword = bool(texts & _SECTION_KEYWORDS.keys())
        is_structural = (g.bold or _mostly_upper(g)) and len(g.spans) >= 2
        if (is_keyword or is_structural) and g.size >= body_size * 0.9:
            roles["section_heading"] = _style(g)
            used.add(i)
            break

    # -- body_paragraph: most common style by character count --
    body_idx = groups.index(body_group)
    if body_idx not in used:
        roles["body_paragraph"] = _style(body_group)
        used.add(body_idx)

    # -- contact: small text near the top --
    for i, g in enumerate(groups):
        if i in used or g.size >= body_size:
            continue
        if any(s.y0 < page_height * 0.2 for s in g.spans):
            roles["contact"] = _style(g)
            used.add(i)
            break

    # -- body_bold: same size tier as body, but bold --
    for i, g in enumerate(groups):
        if i in used or not g.bold:
            continue
        if abs(g.size - body_size) < 1.5:
            roles["body_bold"] = _style(g)
            used.add(i)
            break

    # -- body_italic --
    for i, g in enumerate(groups):
        if i in used or not g.italic:
            continue
        if abs(g.size - body_size) < 1.5:
            roles["body_italic"] = _style(g)
            used.add(i)
            break

    # -- detail: noticeably smaller than body --
    for i, g in enumerate(groups):
        if i in used:
            continue
        if g.size < body_size * 0.88:
            roles["detail"] = _style(g)
            used.add(i)
            break

    return roles


def _to_element_style(
    group: _StyleGroup,
    columns: list[Column],
    all_spans: list[_Span],
) -> ElementStyle:
    """Convert an internal style group into an ElementStyle model."""
    dominant_col = _dominant_column(group.spans)
    col = columns[dominant_col] if dominant_col < len(columns) else columns[0]
    align = _detect_alignment(group.spans, col)
    leading = _leading_for_spans(group.spans)

    bullet_char = ""
    for s in group.spans:
        stripped = s.text.lstrip()
        if stripped and stripped[0] in _BULLET_CHARS:
            bullet_char = stripped[0]
            break

    spacing_before, spacing_after = _spacing_around(group.spans, all_spans)

    return ElementStyle(
        font=group.font,
        size=round(group.size, 2),
        color=group.color,
        bold=group.bold,
        italic=group.italic,
        align=align,
        leading=round(leading, 2),
        bullet_char=bullet_char,
        spacing_before=spacing_before,
        spacing_after=spacing_after,
        col_idx=dominant_col,
    )


# ---------------------------------------------------------------------------
# Step 5 – Section detection
# ---------------------------------------------------------------------------


def _detect_sections(
    spans: list[_Span],
    columns: list[Column],
    element_styles: dict[str, ElementStyle],
) -> dict[str, list[Section]]:
    """Match heading-style spans to known section keywords."""
    sec_map: dict[str, list[Section]] = {col.id: [] for col in columns}

    heading_style = element_styles.get("section_heading")
    if heading_style is None:
        return sec_map

    seen_keys: set[str] = set()
    for s in sorted(spans, key=lambda sp: sp.y0):
        if not _matches_heading(s, heading_style):
            continue

        label = s.text.strip()
        content_key = _SECTION_KEYWORDS.get(label.lower())
        if content_key is None or content_key in seen_keys:
            continue

        col_id = columns[s.col_idx].id if s.col_idx < len(columns) else columns[0].id
        sec_map[col_id].append(Section(label=label, content_key=content_key))
        seen_keys.add(content_key)

    return sec_map


def _matches_heading(span: _Span, style: ElementStyle) -> bool:
    return abs(span.size - style.size) < 0.5 and span.bold == style.bold


# ---------------------------------------------------------------------------
# Step 6 – Spacing metrics
# ---------------------------------------------------------------------------


def _compute_spacing(
    spans: list[_Span],
    element_styles: dict[str, ElementStyle],
    page_height: float,
    drawn_bullets: list[tuple[float, float]],
) -> dict[str, float]:
    """Derive line, section, and entry spacing from vertical gaps.

    Deduplicates spans on the same y-line before measuring y0-to-y0
    (baseline-to-baseline) distances, which is more stable than gap-between-boxes.
    """
    defaults = {
        "line_spacing": 14.0,
        "section_spacing": 24.0,
        "entry_spacing": 14.0,
        "bullet_indent": 10.0,
    }
    if len(spans) < 2:
        return defaults

    line_ys = _unique_line_ys(spans)

    baseline_dists: list[float] = []
    for a_y, b_y in zip(line_ys, line_ys[1:]):
        dist = b_y - a_y
        if 0 < dist < page_height * 0.15:
            baseline_dists.append(dist)

    if not baseline_dists:
        return defaults

    median_dist = statistics.median(baseline_dists)
    line_sp = round(median_dist, 1)

    large = [d for d in baseline_dists if d > median_dist * 1.8]
    section_sp = round(statistics.median(large), 1) if large else round(line_sp * 1.7, 1)

    mid = [d for d in baseline_dists if median_dist * 1.2 < d <= median_dist * 1.8]
    entry_sp = round(statistics.median(mid), 1) if mid else round(line_sp * 1.1, 1)

    body_style = element_styles.get("body_paragraph")
    bullet_indent = _compute_bullet_indent(spans, body_style, drawn_bullets)

    return {
        "line_spacing": line_sp,
        "section_spacing": section_sp,
        "entry_spacing": entry_sp,
        "bullet_indent": bullet_indent,
    }


def _compute_bullet_indent(
    spans: list[_Span],
    body_style: ElementStyle | None,
    drawn_bullets: list[tuple[float, float]],
) -> float:
    """Measure indentation of bullet lines relative to non-bullet text.

    Considers both text bullet characters and drawn bullet squares.
    """
    bullet_x: list[float] = []
    body_x: list[float] = []

    for s in spans:
        stripped = s.text.lstrip()
        if stripped and stripped[0] in _BULLET_CHARS:
            bullet_x.append(s.x0)
        elif body_style and abs(s.size - body_style.size) < 0.5:
            body_x.append(s.x0)

    if not bullet_x and drawn_bullets:
        bullet_x = [bx for bx, _ in drawn_bullets]

    if not bullet_x or not body_x:
        return 10.0

    indent = abs(statistics.median(bullet_x) - statistics.median(body_x))
    return round(indent, 1) if indent > 0.5 else 10.0


# ---------------------------------------------------------------------------
# Step 7 – Format heuristics
# ---------------------------------------------------------------------------


def _find_drawn_bullets(page: fitz.Page) -> list[tuple[float, float]]:
    """Detect small filled squares used as bullet markers.

    Returns (x_centre, y_centre) for each detected bullet.
    """
    bullets: list[tuple[float, float]] = []
    for path in page.get_drawings():
        fill = path.get("fill")
        if fill is None:
            continue
        rect = path.get("rect")
        if rect is None:
            continue
        w, h = abs(rect.width), abs(rect.height)
        if w < 1 or h < 1:
            continue
        if w <= _MAX_DRAWN_BULLET_SIZE and h <= _MAX_DRAWN_BULLET_SIZE:
            cx = (rect.x0 + rect.x1) / 2
            cy = (rect.y0 + rect.y1) / 2
            bullets.append((cx, cy))
    return bullets


def _detect_formats(
    spans: list[_Span],
    drawn_bullets: list[tuple[float, float]],
    element_styles: dict[str, ElementStyle] | None = None,
) -> dict[str, str]:
    """Infer skill_format, job_entry_format, and job_body_format."""
    has_text_bullets = any(
        s.text.lstrip()[:1] in _BULLET_CHARS for s in spans if s.text.strip()
    )
    has_drawn_bullets = len(drawn_bullets) >= 3
    has_comma_lists = any("," in s.text and len(s.text.split(",")) >= 3 for s in spans)

    return {
        "skill_format": "inline" if has_comma_lists else "list",
        "job_entry_format": _detect_job_entry_format(spans, element_styles),
        "job_body_format": "bullet" if (has_text_bullets or has_drawn_bullets) else "paragraph",
    }


def _detect_job_entry_format(
    spans: list[_Span],
    element_styles: dict[str, ElementStyle] | None,
) -> str:
    """Detect whether company+title lines are single-line or two-line.

    Looks for bold spans (company names) and italic spans (job titles) that
    appear at roughly the same y-position (within 3pt).  If several such
    pairs exist the format is ``single_line``; otherwise ``two_line``.
    """
    if not element_styles:
        return "two_line"

    bold_style = element_styles.get("body_bold")
    italic_style = element_styles.get("body_italic")
    if bold_style is None or italic_style is None:
        return "two_line"

    bold_ys = sorted(
        s.y0 for s in spans
        if s.bold and abs(s.size - bold_style.size) < 1.0
    )
    italic_ys = sorted(
        s.y0 for s in spans
        if s.italic and abs(s.size - italic_style.size) < 1.0
    )

    same_line_count = 0
    for by in bold_ys:
        for iy in italic_ys:
            if abs(by - iy) < 3.0:
                same_line_count += 1
                break

    return "single_line" if same_line_count >= 2 else "two_line"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _srgb_int_to_floats(value: int) -> tuple[float, float, float]:
    """Convert packed sRGB integer to (r, g, b) floats in [0, 1]."""
    return (
        round(((value >> 16) & 0xFF) / 255.0, 3),
        round(((value >> 8) & 0xFF) / 255.0, 3),
        round((value & 0xFF) / 255.0, 3),
    )


def _normalize_drawing_color(
    fill: tuple | list | float | None,
) -> tuple[float, float, float] | None:
    """Coerce a PyMuPDF drawing fill value to an (r, g, b) tuple."""
    if fill is None:
        return None
    if isinstance(fill, (int, float)):
        v = float(fill)
        return (v, v, v)
    if isinstance(fill, (list, tuple)):
        if len(fill) >= 3:
            return (float(fill[0]), float(fill[1]), float(fill[2]))
        if len(fill) == 1:
            return (float(fill[0]), float(fill[0]), float(fill[0]))
    return None


def _clean_font_name(raw: str) -> str:
    """Strip subset prefix and Type3 object references.

    'AAAAAA+Lato-Regular' -> 'Lato-Regular'
    'Type3 (8 0 R)' -> 'Type3'
    """
    name = raw.split("+", 1)[-1] if "+" in raw else raw
    if name.startswith("Type3"):
        return "Type3"
    return name


def _font_name_indicates(font: str, keywords: tuple[str, ...]) -> bool:
    low = font.lower()
    return any(k in low for k in keywords)


def _mostly_upper(group: _StyleGroup) -> bool:
    """True if most spans are all-uppercase text (length > 2)."""
    upper = sum(
        1 for s in group.spans if s.text.strip() == s.text.strip().upper() and len(s.text.strip()) > 2
    )
    return upper > len(group.spans) * 0.6


def _dominant_column(spans: list[_Span]) -> int:
    """Column index containing the majority of spans."""
    if not spans:
        return 0
    counts: dict[int, int] = {}
    for s in spans:
        counts[s.col_idx] = counts.get(s.col_idx, 0) + 1
    return max(counts, key=lambda k: counts[k])


def _detect_alignment(spans: list[_Span], col: Column) -> str:
    """Infer text alignment from span positions within a column."""
    col_w = col.x1 - col.x0
    if not spans or col_w < 1:
        return "left"

    left_offsets = [s.x0 - col.x0 for s in spans]
    right_offsets = [col.x1 - s.x1 for s in spans]

    avg_left = statistics.mean(left_offsets)
    avg_right = statistics.mean(right_offsets)

    if abs(avg_left - avg_right) < col_w * 0.1:
        return "center"

    if len(spans) > 1:
        left_var = statistics.variance(left_offsets)
        right_var = statistics.variance(right_offsets)
        if right_var < left_var * 0.3 and avg_right < avg_left:
            return "right"

    return "left"


def _leading_for_spans(spans: list[_Span]) -> float:
    """Compute typical baseline-to-baseline distance for a set of spans.

    Falls back to ``size * 1.35`` when fewer than two spans exist or no
    measurable gaps are found (avoids returning 0.0 which would cause
    overlapping text in the generator).
    """
    fallback = spans[0].size * 1.35 if spans else 0.0

    if len(spans) < 2:
        return fallback

    by_y = sorted(spans, key=lambda s: s.y0)
    gaps = [
        by_y[i + 1].y0 - by_y[i].y0
        for i in range(len(by_y) - 1)
        if 0 < by_y[i + 1].y0 - by_y[i].y0 < 40
    ]
    return statistics.median(gaps) if gaps else fallback


def _unique_line_ys(spans: list[_Span], tolerance: float = 3.0) -> list[float]:
    """Collapse spans that share the same y-line into unique y-positions.

    Spans whose y0 values are within *tolerance* of each other are treated
    as being on the same line; the median y0 is kept.
    """
    ys = sorted(s.y0 for s in spans)
    if not ys:
        return []

    lines: list[list[float]] = [[ys[0]]]
    for y in ys[1:]:
        if y - lines[-1][-1] <= tolerance:
            lines[-1].append(y)
        else:
            lines.append([y])

    return [statistics.median(group) for group in lines]


def _spacing_around(
    group_spans: list[_Span],
    all_spans: list[_Span],
) -> tuple[float, float]:
    """Estimate spacing_before and spacing_after for a style group.

    Measures the vertical gap between each span in *group_spans* and its
    nearest neighbour from a *different* style group, giving true
    inter-group spacing rather than intra-group distances.
    """
    if not group_spans or len(all_spans) < 2:
        return (4.0, 2.0)

    group_set = set(id(s) for s in group_spans)
    others = sorted(
        (s for s in all_spans if id(s) not in group_set),
        key=lambda s: s.y0,
    )
    if not others:
        return (4.0, 2.0)

    other_ys = [s.y0 for s in others]
    other_y1s = [s.y1 for s in others]

    before: list[float] = []
    after: list[float] = []

    for gs in group_spans:
        idx = bisect.bisect_right(other_ys, gs.y0)

        if idx > 0:
            gap = gs.y0 - other_y1s[idx - 1]
            if 0 < gap < 60:
                before.append(gap)

        if idx < len(others):
            gap = other_ys[idx] - gs.y1
            if 0 < gap < 60:
                after.append(gap)

    sb = round(statistics.median(before), 1) if before else 4.0
    sa = round(statistics.median(after), 1) if after else 2.0
    return (sb, sa)
