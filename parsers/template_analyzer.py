"""
Template Analyzer - Extracts visual theme and structural geometry from a PDF
template using PyMuPDF.

Extracts colors, fonts, sizes, margins, sidebar layout, header geometry,
section bar dimensions, line spacing, and column regions.
"""
from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

import fitz  # PyMuPDF


# Minimum fraction of page area a rectangle must cover to be considered a
# structural background element (not a tiny accent or bullet symbol).
_SECTION_BAR_MIN_FRAC = 0.005


def analyze(source_path: str) -> dict[str, Any]:
    """
    Open *source_path* and return a comprehensive TemplateTheme dict.

    Returns
    -------
    dict with keys:
        header_bg          – (r, g, b) floats 0-1, topmost large colored rect
        section_bg         – (r, g, b) floats 0-1, section-header bar color
        header_text_color  – (r, g, b) floats 0-1, text sitting on header_bg
        body_text_color    – (r, g, b) floats 0-1, dominant body text color
        name_font_size     – float, largest font size found
        heading_font_size  – float, second-largest font size found
        body_font_size     – float, most common font size
        left_margin        – float (points)
        right_margin       – float (points)
        top_margin         – float (points)
        bottom_margin      – float (points)
        page_width         – float (points)
        page_height        – float (points)
        layout_type        – "single_column" | "left_sidebar" | "right_sidebar"
        sidebar_width      – float (points), 0 if no sidebar
        sidebar_color      – (r, g, b) floats 0-1, sidebar background color
        sidebar_side       – "left" | "right" | None
        header_height      – float (points), vertical extent of the header region
        header_full_width  – bool, True if header rect spans edge-to-edge
        section_bar_height – float (points), typical height of section header bars
        line_spacing       – float (points), vertical distance between text lines
        section_spacing    – float (points), vertical gap between content sections
        columns            – list of {"x0": float, "x1": float} per column
    """
    doc = fitz.open(source_path)
    try:
        return _analyze_doc(doc)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _analyze_doc(doc: fitz.Document) -> dict[str, Any]:
    page = doc[0]
    page_w = page.rect.width
    page_h = page.rect.height
    page_area = page_w * page_h

    # ── Collect colored rectangles with full geometry ──────────────────────
    # Store: (y0, area, color, x0, x1, y1, width, height)
    colored_rects: list[tuple] = []

    for d in page.get_drawings():
        fill = d.get("fill")
        if not fill or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        # Skip near-white (page background)
        if r > 0.92 and g > 0.92 and b > 0.92:
            continue
        # Skip near-black text/hairline rules
        if r < 0.08 and g < 0.08 and b < 0.08:
            continue
        rect = fitz.Rect(d.get("rect", [0, 0, 0, 0]))
        if rect.is_empty:
            continue
        area = rect.width * rect.height
        if area < page_area * _SECTION_BAR_MIN_FRAC:
            continue
        colored_rects.append((
            rect.y0, area, (r, g, b),
            rect.x0, rect.x1, rect.y1,
            rect.width, rect.height,
        ))

    # Sort by y position (top to bottom)
    colored_rects.sort(key=lambda x: x[0])

    # ── Sidebar detection ──────────────────────────────────────────────────
    # A sidebar is a tall colored rect that covers ≥ 50% of page height
    # and ≤ 45% of page width — indicates a column panel background.
    layout_type = "single_column"
    sidebar_width: float = 0.0
    sidebar_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    sidebar_side: str | None = None

    for entry in colored_rects:
        _, _, color, x0, x1, y1, w, h = entry
        if h >= page_h * 0.5 and w <= page_w * 0.45:
            sidebar_width = w
            sidebar_color = color
            sidebar_side = "left" if x0 < page_w / 2 else "right"
            layout_type = "left_sidebar" if sidebar_side == "left" else "right_sidebar"
            break

    # ── Header bg color + header geometry ─────────────────────────────────
    header_bg: tuple[float, float, float] = (0.2, 0.2, 0.2)
    section_bg: tuple[float, float, float] = (0.3, 0.3, 0.3)
    header_height: float = 0.0
    header_full_width: bool = False

    # Filter out the sidebar from "header" candidates
    non_sidebar_rects = [
        entry for entry in colored_rects
        if entry[6] < page_w * 0.45 or entry[7] < page_h * 0.5
    ]

    # The topmost non-sidebar colored rect that spans most of the page width
    # (or the topmost of any rect if none spans wide) → header
    wide_rects = [e for e in non_sidebar_rects if e[6] >= page_w * 0.4]
    header_candidates = wide_rects if wide_rects else non_sidebar_rects

    if header_candidates:
        top_entry = header_candidates[0]
        _, _, color, x0, x1, y1, w, h = top_entry
        header_bg = color
        header_height = y1  # y1 in PDF coords = bottom of the rect (top-down)
        header_full_width = x0 < 5.0 and x1 > page_w - 5.0

        # Section bars: subsequent wide rects with different color
        for entry in header_candidates[1:]:
            _, _, entry_color, *_ = entry
            if _color_distance(entry_color, header_bg) > 0.05:
                section_bg = entry_color
                break
        else:
            section_bg = header_bg
    elif colored_rects:
        # Fall back to any rect
        top_entry = colored_rects[0]
        _, _, color, x0, x1, y1, w, h = top_entry
        header_bg = color
        header_height = y1
        header_full_width = x0 < 5.0 and x1 > page_w - 5.0
        section_bg = header_bg

    # ── Section bar height ─────────────────────────────────────────────────
    # Section bars are wide rects (≥ 40% page width) that are NOT the header
    # and are relatively thin (height < 40 pt).
    bar_heights: list[float] = []
    for entry in colored_rects:
        _, area, color, x0, x1, y1, w, h = entry
        if w >= page_w * 0.4 and 4 < h < 40 and y1 > header_height:
            bar_heights.append(h)

    section_bar_height: float = (
        statistics.median(bar_heights) if bar_heights else 16.0
    )

    # ── Extract text spans ─────────────────────────────────────────────────
    text_dict = page.get_text("dict")
    all_spans: list[dict] = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    all_spans.append(span)

    # ── Font sizes ─────────────────────────────────────────────────────────
    sizes = [round(s.get("size", 11), 1) for s in all_spans]
    size_counter = Counter(sizes)
    unique_sizes = sorted(size_counter.keys())

    body_font_size = float(size_counter.most_common(1)[0][0]) if size_counter else 10.0
    name_font_size = float(max(unique_sizes)) if unique_sizes else 22.0
    heading_font_size = float(unique_sizes[-2]) if len(unique_sizes) >= 2 else body_font_size + 1

    # ── Body text color ────────────────────────────────────────────────────
    body_color_raw = _dominant_color(
        [s for s in all_spans if abs(s.get("size", 0) - body_font_size) < 1.5]
    )
    body_text_color = _normalize_span_color(body_color_raw)

    # ── Header text color ──────────────────────────────────────────────────
    header_spans = [s for s in all_spans if abs(s.get("size", 0) - name_font_size) < 2]
    if header_spans:
        header_color_raw = _dominant_color(header_spans)
        header_text_color = _normalize_span_color(header_color_raw)
    else:
        header_text_color = (1.0, 1.0, 1.0)

    # ── Margins from content bounds ────────────────────────────────────────
    # For sidebar layouts, use the content column bounds for margins.
    if layout_type == "left_sidebar":
        content_spans = [
            s for s in all_spans
            if s.get("bbox", [0])[0] >= sidebar_width * 0.9
        ]
    elif layout_type == "right_sidebar":
        content_spans = [
            s for s in all_spans
            if s.get("bbox", [0, 0, 0, 0])[2] <= page_w - sidebar_width * 0.9
        ]
    else:
        content_spans = all_spans

    x0s = [s.get("bbox", [0, 0, 0, 0])[0] for s in content_spans] if content_spans else [s.get("bbox", [0, 0, 0, 0])[0] for s in all_spans]
    x1s = [s.get("bbox", [0, 0, 0, 0])[2] for s in content_spans] if content_spans else [s.get("bbox", [0, 0, 0, 0])[2] for s in all_spans]
    y0s = [s.get("bbox", [0, 0, 0, 0])[1] for s in all_spans]
    y1s = [s.get("bbox", [0, 0, 0, 0])[3] for s in all_spans]

    if layout_type == "left_sidebar":
        left_margin = float(min(x0s)) if x0s else sidebar_width + 10.0
        right_margin = float(page_w - max(x1s)) if x1s else 28.0
    elif layout_type == "right_sidebar":
        left_margin = float(min(x0s)) if x0s else 28.0
        right_margin = float(page_w - (page_w - sidebar_width) - max(x1s)) if x1s else sidebar_width + 10.0
    else:
        left_margin = float(min(x0s)) if x0s else 36.0
        right_margin = float(page_w - max(x1s)) if x1s else 36.0

    top_margin = float(min(y0s)) if y0s else 0.0
    bottom_margin = float(page_h - max(y1s)) if y1s else 28.0

    # Don't clamp left/right to 72 for sidebar layouts — sidebars can push
    # margins well beyond 72 pts. Use a wider sensible range.
    left_margin = max(0.0, min(page_w * 0.4, left_margin))
    right_margin = max(0.0, min(page_w * 0.4, right_margin))
    top_margin = max(0.0, min(72.0, top_margin))
    bottom_margin = max(0.0, min(72.0, bottom_margin))

    # ── Line spacing ───────────────────────────────────────────────────────
    # Group body-size spans by approximate x-column and compute median
    # vertical gap between consecutive lines.
    body_spans = [
        s for s in all_spans if abs(s.get("size", 0) - body_font_size) < 2.0
    ]
    body_spans.sort(key=lambda s: (round(s["bbox"][0] / 50) * 50, s["bbox"][1]))

    line_gaps: list[float] = []
    prev_y1: float | None = None
    prev_col: int | None = None
    for s in body_spans:
        bbox = s.get("bbox", [0, 0, 0, 0])
        col = round(bbox[0] / 50) * 50
        y0 = bbox[1]
        if prev_y1 is not None and col == prev_col:
            gap = y0 - prev_y1
            if 0 < gap < body_font_size * 3:
                line_gaps.append(gap)
        prev_y1 = bbox[3]
        prev_col = col

    line_spacing: float = (
        statistics.median(line_gaps) + body_font_size
        if line_gaps
        else body_font_size * 1.4
    )

    # ── Section spacing ────────────────────────────────────────────────────
    # Large vertical gaps in the main content column indicate section breaks.
    main_spans = sorted(
        [s for s in all_spans if abs(s.get("size", 0) - body_font_size) < 3],
        key=lambda s: s["bbox"][1],
    )
    section_gaps: list[float] = []
    for i in range(1, len(main_spans)):
        gap = main_spans[i]["bbox"][1] - main_spans[i - 1]["bbox"][3]
        if gap > body_font_size * 1.5:
            section_gaps.append(gap)
    section_spacing: float = (
        statistics.median(section_gaps) if section_gaps else 8.0
    )
    # Clamp to a reasonable range
    section_spacing = max(4.0, min(24.0, section_spacing))

    # ── Column regions ─────────────────────────────────────────────────────
    if layout_type == "left_sidebar":
        columns = [
            {"x0": 0.0, "x1": sidebar_width},
            {"x0": sidebar_width, "x1": page_w},
        ]
    elif layout_type == "right_sidebar":
        columns = [
            {"x0": 0.0, "x1": page_w - sidebar_width},
            {"x0": page_w - sidebar_width, "x1": page_w},
        ]
    else:
        columns = [{"x0": left_margin, "x1": page_w - right_margin}]

    return {
        # ── Existing color / font keys ──────────────────────────────────
        "header_bg": header_bg,
        "section_bg": section_bg,
        "header_text_color": header_text_color,
        "body_text_color": body_text_color,
        "name_font_size": name_font_size,
        "heading_font_size": heading_font_size,
        "body_font_size": body_font_size,
        # ── Margins ─────────────────────────────────────────────────────
        "left_margin": left_margin,
        "right_margin": right_margin,
        "top_margin": top_margin,
        "bottom_margin": bottom_margin,
        # ── Page dimensions ─────────────────────────────────────────────
        "page_width": page_w,
        "page_height": page_h,
        # ── NEW structural geometry ──────────────────────────────────────
        "layout_type": layout_type,
        "sidebar_width": sidebar_width,
        "sidebar_color": sidebar_color,
        "sidebar_side": sidebar_side,
        "header_height": header_height,
        "header_full_width": header_full_width,
        "section_bar_height": section_bar_height,
        "line_spacing": line_spacing,
        "section_spacing": section_spacing,
        "columns": columns,
    }


def _dominant_color(spans: list[dict]) -> Any:
    """Return the most common raw color value among *spans*."""
    if not spans:
        return 0
    counts: Counter = Counter(s.get("color", 0) for s in spans)
    return counts.most_common(1)[0][0]


def _normalize_span_color(raw: Any) -> tuple[float, float, float]:
    """Convert a PyMuPDF integer or tuple color to an (r, g, b) 0-1 float tuple."""
    if isinstance(raw, (tuple, list)) and len(raw) >= 3:
        vals = [float(v) for v in raw[:3]]
        if any(v > 1.0 for v in vals):
            return (vals[0] / 255, vals[1] / 255, vals[2] / 255)
        return (vals[0], vals[1], vals[2])
    if isinstance(raw, int):
        r = (raw >> 16) & 0xFF
        g = (raw >> 8) & 0xFF
        b = raw & 0xFF
        return (r / 255.0, g / 255.0, b / 255.0)
    return (0.0, 0.0, 0.0)


def _color_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def theme_to_css(theme: dict[str, Any]) -> dict[str, str]:
    """Convert a TemplateTheme dict to CSS hex strings for use in the browser preview."""
    return {
        "header_bg": _rgb_to_hex(theme["header_bg"]),
        "section_bg": _rgb_to_hex(theme["section_bg"]),
        "header_text_color": _rgb_to_hex(theme["header_text_color"]),
        "body_text_color": _rgb_to_hex(theme["body_text_color"]),
        "name_font_size": str(round(theme["name_font_size"])),
        "heading_font_size": str(round(theme["heading_font_size"])),
        "body_font_size": str(round(theme["body_font_size"], 1)),
    }


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = rgb
    return "#{:02x}{:02x}{:02x}".format(
        int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
    )
