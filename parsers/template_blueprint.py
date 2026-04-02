"""
Template Blueprint Extractor

Analyzes a PDF template and returns a rich structural blueprint:
  - background_regions: exact colored rectangles to draw on canvas (edge-to-edge)
  - columns: text frame positions from colored-rect and/or text-cluster detection
  - element_styles: per-semantic-type visual style catalog
  - section_map: which sections appear in which column, in order
  - skill_format / job_entry_format: format variants for rendering
  - spacing: line_spacing, section_spacing, entry_spacing, bullet_indent

All 7 analyzed template patterns are handled:
  single-column, left-sidebar (colored), left-sidebar (text-only),
  right-sidebar, inline skills, heading+items skills, flat-list skills,
  bullet experience, paragraph experience, name-in-sidebar.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from typing import Any

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Constants / lookup tables
# ---------------------------------------------------------------------------

# Canonical section-type lookup (substring match, lower-case)
_SECTION_KEYWORDS: list[tuple[str, str]] = [
    ("professional summary", "summary"),
    ("profile summary", "summary"),
    ("technical skill", "skills"),
    ("areas of expertise", "expertise"),
    ("skill", "skills"),
    ("experience", "experience"),
    ("employment", "experience"),
    ("work history", "experience"),
    ("work experience", "experience"),
    ("project", "projects"),
    ("education", "education"),
    ("academic", "education"),
    ("contact", "contact"),
    ("summary", "summary"),
    ("profile", "summary"),
    ("objective", "summary"),
    ("about me", "summary"),
    ("certification", "certifications"),
    ("award", "awards"),
    ("publication", "publications"),
    ("article", "publications"),
    ("talk", "publications"),
    ("volunteer", "volunteer"),
    ("language", "languages"),
    ("expertise", "expertise"),
    ("interest", "interests"),
]

_DATE_RE = re.compile(
    r"(?:"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{4}"
    r"|"
    r"\d{4}\s*[-\u2013\u2014]\s*(?:\d{4}|Present|Now|Current|present|now|current)"
    r"|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s*\d{4}"
    r")",
    re.IGNORECASE,
)

_PHONE_RE = re.compile(r"\+?\d[\d\s\-(). ]{5,}\d")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_URL_RE   = re.compile(r"(?:linkedin|github|http|www\.|\.com/|\.io/)", re.IGNORECASE)
_SKILL_INLINE_RE = re.compile(r"^([A-Z][A-Z0-9\s&/'`+*#.,-]{0,40}):\s*(.+)$", re.DOTALL)

# Minimum area fraction for a fill rect to be a background element
_BG_MIN_AREA_FRAC = 0.003
# Points gap between two x-clusters to declare a two-column layout
_COL_GAP_MIN = 20.0
# Fraction of page height a rect must cover to be a sidebar
_SIDEBAR_HEIGHT_FRAC = 0.45
# Fraction of page width a rect must be at most to be a sidebar (not full-width)
_SIDEBAR_MAX_WIDTH_FRAC = 0.48


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_blueprint(source_path: str) -> dict[str, Any]:
    """
    Open *source_path* and return a complete TemplateBlueprint dict.

    The returned dict is JSON-serializable.
    """
    doc = fitz.open(source_path)
    try:
        return _analyze(doc)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Core analysis pipeline
# ---------------------------------------------------------------------------

def _analyze(doc: fitz.Document) -> dict[str, Any]:
    page = doc[0]
    pw: float = page.rect.width
    ph: float = page.rect.height

    # ── Step 1: background regions ─────────────────────────────────────────
    bg_regions = _extract_bg_regions(page, pw, ph)

    # ── Step 2: text blocks with dominant style ────────────────────────────
    blocks = _extract_blocks(page, pw)

    # ── Step 3: column layout ──────────────────────────────────────────────
    columns, layout_type = _detect_columns(pw, ph, bg_regions, blocks)

    # ── Step 4: assign blocks to columns ──────────────────────────────────
    for blk in blocks:
        blk["col_idx"] = _assign_col(blk["bbox"], columns)

    # ── Step 5: font size hierarchy ────────────────────────────────────────
    # Exclude sub-4pt invisible/watermark text from all analysis
    blocks = [b for b in blocks if b["size"] >= 4.0 or not b["text"].strip()]
    text_blocks = [b for b in blocks if b["text"].strip()]
    sizes = [round(b["size"], 1) for b in text_blocks]
    size_ctr = Counter(sizes)
    body_size = float(size_ctr.most_common(1)[0][0]) if size_ctr else 10.0
    sorted_sizes = sorted(size_ctr.keys())
    name_size = float(sorted_sizes[-1]) if sorted_sizes else 22.0
    # heading_size: largest size that's clearly above body
    heading_size = next(
        (s for s in reversed(sorted_sizes) if s > body_size * 1.08),
        body_size * 1.15,
    )

    # ── Step 6: find name and title/subtitle blocks ────────────────────────
    name_blk, title_blk = _find_identity(blocks, name_size, heading_size, body_size)

    # ── Step 7: walk each column, label sections, build element_styles ─────
    element_styles: dict[str, dict] = {}
    format_flags: dict[str, str] = {}
    section_map: dict[str, list] = {}

    blocks_per_col: dict[int, list] = defaultdict(list)
    for blk in blocks:
        blocks_per_col[blk["col_idx"]].append(blk)
    for col_blks in blocks_per_col.values():
        col_blks.sort(key=lambda b: b["bbox"][1])

    for col_idx in range(len(columns)):
        col_blks = blocks_per_col.get(col_idx, [])
        sections, ff = _walk_column(
            col_blks, col_idx, name_blk, title_blk,
            body_size, heading_size, bg_regions, pw, element_styles,
        )
        section_map[f"col_{col_idx}"] = [
            {"type": s["type"], "heading_text": s.get("heading_text", "")}
            for s in sections
        ]
        format_flags.update(ff)

    # Ensure element_styles always has a usable section_heading entry
    _ensure_section_heading_style(element_styles, body_size)

    # ── Step 7b: move identity to main column when name is in full-width header ──
    _normalize_identity_placement(section_map, layout_type, name_blk, bg_regions, pw)

    # ── Step 8: spacing values ─────────────────────────────────────────────
    spacing = _compute_spacing(blocks, body_size)

    # ── Step 9: name column ────────────────────────────────────────────────
    name_col_idx = name_blk["col_idx"] if name_blk else 0

    return {
        "page_width": pw,
        "page_height": ph,
        "layout_type": layout_type,
        "background_regions": bg_regions,
        "columns": columns,
        "element_styles": element_styles,
        "section_map": section_map,
        "name_col_idx": name_col_idx,
        **format_flags,
        **spacing,
    }


# ---------------------------------------------------------------------------
# Step 1 – Background regions
# ---------------------------------------------------------------------------

def _extract_bg_regions(page: fitz.Page, pw: float, ph: float) -> list[dict]:
    """Return all non-white, non-black filled rects above the area threshold."""
    regions: list[dict] = []
    page_area = pw * ph

    for d in page.get_drawings():
        fill = d.get("fill")
        if not fill or len(fill) < 3:
            continue
        r, g, b = float(fill[0]), float(fill[1]), float(fill[2])
        if r > 0.92 and g > 0.92 and b > 0.92:
            continue  # near-white
        if r < 0.06 and g < 0.06 and b < 0.06:
            continue  # near-black
        rect = fitz.Rect(d.get("rect", [0, 0, 0, 0]))
        if rect.is_empty:
            continue
        if rect.width * rect.height < page_area * _BG_MIN_AREA_FRAC:
            continue
        regions.append({
            "x0": rect.x0, "y0": rect.y0,
            "x1": rect.x1, "y1": rect.y1,
            "width": rect.width, "height": rect.height,
            "color": [r, g, b],
        })

    # Sort top-to-bottom
    regions.sort(key=lambda r: r["y0"])
    return regions


# ---------------------------------------------------------------------------
# Step 2 – Text block extraction
# ---------------------------------------------------------------------------

def _extract_blocks(page: fitz.Page, pw: float) -> list[dict]:
    """Extract all text blocks with their dominant visual style."""
    result: list[dict] = []
    raw = page.get_text("dict")

    for raw_blk in raw.get("blocks", []):
        if raw_blk.get("type") != 0:
            continue

        bbox = raw_blk.get("bbox", [0, 0, 0, 0])
        lines_data = raw_blk.get("lines", [])

        # Collect all spans
        all_spans: list[dict] = []
        for line in lines_data:
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    all_spans.append(span)

        if not all_spans:
            continue

        # Dominant style from spans (weighted by text length)
        def _w(s: dict) -> int:
            return max(len(s.get("text", "")), 1)

        total_w = sum(_w(s) for s in all_spans)
        dom_size = sum(s.get("size", 10) * _w(s) for s in all_spans) / total_w
        dom_flags = Counter(s.get("flags", 0) for s in all_spans).most_common(1)[0][0]
        dom_color_raw = Counter(s.get("color", 0) for s in all_spans).most_common(1)[0][0]
        dom_font = Counter(s.get("font", "").split("+")[-1] for s in all_spans).most_common(1)[0][0]

        bold = bool(dom_flags & 16)
        italic = bool(dom_flags & 2)
        color = _int_to_rgb(dom_color_raw)

        # Full text (all lines joined)
        lines_text = []
        for line in lines_data:
            line_text = "".join(sp.get("text", "") for sp in line.get("spans", []))
            if line_text.strip():
                lines_text.append(line_text.rstrip())
        full_text = "\n".join(lines_text)

        # Alignment heuristic
        blk_cx = (bbox[0] + bbox[2]) / 2
        page_cx = pw / 2
        if abs(blk_cx - page_cx) < pw * 0.10:
            align = "center"
        elif bbox[2] >= pw * 0.85 and bbox[0] > pw * 0.45:
            align = "right"
        else:
            align = "left"

        result.append({
            "bbox": list(bbox),
            "text": full_text,
            "font": dom_font,
            "size": dom_size,
            "bold": bold,
            "italic": italic,
            "color": color,
            "align": align,
            "col_idx": 0,  # filled in later
        })

    return result


# ---------------------------------------------------------------------------
# Step 3 – Column detection
# ---------------------------------------------------------------------------

def _detect_columns(
    pw: float, ph: float,
    bg_regions: list[dict],
    blocks: list[dict],
) -> tuple[list[dict], str]:
    """
    Return (columns, layout_type).

    Pass 1: look for a tall colored rect that is a sidebar.
    Pass 2: if no colored sidebar, cluster text x0 positions to find a gap.
    """
    # --- Pass 1: colored sidebar rect ---
    for reg in bg_regions:
        if reg["height"] >= ph * _SIDEBAR_HEIGHT_FRAC and reg["width"] <= pw * _SIDEBAR_MAX_WIDTH_FRAC:
            side = "left" if reg["x0"] < pw / 2 else "right"
            boundary = reg["x1"] if side == "left" else reg["x0"]
            gap = 8.0
            if side == "left":
                cols = [
                    {"id": "col_0", "x0": reg["x0"], "x1": reg["x1"],
                     "y_top": ph, "y_bottom": 0},
                    {"id": "col_1", "x0": boundary + gap, "x1": pw,
                     "y_top": ph, "y_bottom": 0},
                ]
                layout_type = "left_sidebar"
            else:
                cols = [
                    {"id": "col_0", "x0": 0, "x1": boundary - gap,
                     "y_top": ph, "y_bottom": 0},
                    {"id": "col_1", "x0": reg["x0"], "x1": reg["x1"],
                     "y_top": ph, "y_bottom": 0},
                ]
                layout_type = "right_sidebar"
            return cols, layout_type

    # --- Pass 2: block CENTER-X clustering (robust to centered layouts) ---
    # Use the horizontal center (cx) of each block rather than x0.
    # Filter out invisible/tiny blocks (e.g. watermark text at size < 4pt)
    # which scatter across the page and corrupt the clustering.
    visible = [
        b for b in blocks
        if b["text"].strip()
        and b["size"] >= 4.0
        and (b["bbox"][3] - b["bbox"][1]) >= 3.0  # block height >= 3pt
    ]
    cx_vals = [(b["bbox"][0] + b["bbox"][2]) / 2 for b in visible]

    if len(cx_vals) < 4:
        return _single_col(pw, ph), "single_column"

    cx_sorted = sorted(set(round(x) for x in cx_vals))

    best_gap = 0.0
    best_boundary = None
    for i in range(len(cx_sorted) - 1):
        gap = cx_sorted[i + 1] - cx_sorted[i]
        mid = (cx_sorted[i] + cx_sorted[i + 1]) / 2
        # The gap must lie between 10 % and 75 % of page width
        if gap > best_gap and pw * 0.10 < mid < pw * 0.75:
            best_gap = gap
            best_boundary = mid

    # Require a substantial gap AND both clusters to be non-trivial
    if best_gap >= _COL_GAP_MIN and best_boundary is not None:
        left_blks  = [b for b in visible if (b["bbox"][0]+b["bbox"][2])/2 < best_boundary]
        right_blks = [b for b in visible if (b["bbox"][0]+b["bbox"][2])/2 >= best_boundary]
        # Both clusters must contain at least 12 % of blocks
        min_frac = max(2, len(cx_vals) * 0.12)
        if len(left_blks) >= min_frac and len(right_blks) >= min_frac:
            # Verify the two clusters OVERLAP vertically (a true sidebar has
            # content on both sides at the same y-range; a skills grid or
            # sectional layout does not).
            left_y0  = min(b["bbox"][1] for b in left_blks)
            left_y1  = max(b["bbox"][3] for b in left_blks)
            right_y0 = min(b["bbox"][1] for b in right_blks)
            right_y1 = max(b["bbox"][3] for b in right_blks)
            overlap  = min(left_y1, right_y1) - max(left_y0, right_y0)
            # For a true sidebar at least 25 % of page height must overlap
            if overlap < ph * 0.25:
                return _single_col(pw, ph), "single_column"

            # A real sidebar column must contain body text, not just section
            # headings and icon glyphs.  Resumes where section labels sit in a
            # narrow left margin (e.g. "SKILLS", "EMPLOYMENT") while all body
            # content spans the full page width produce a false left cluster of
            # pure headings — reject that case here.
            if not _has_sidebar_body(left_blks):
                return _single_col(pw, ph), "single_column"

            # Determine layout type by which side's cx is narrower
            left_cx_max = max((b["bbox"][0]+b["bbox"][2])/2 for b in left_blks)
            if left_cx_max < pw * 0.40:
                layout_type = "left_sidebar"
            else:
                layout_type = "right_sidebar"
            # Derive actual column x-boundary from block extents
            left_x1  = max(b["bbox"][2] for b in left_blks)
            right_x0 = min(b["bbox"][0] for b in right_blks)
            col_boundary = (left_x1 + right_x0) / 2
            cols = [
                {"id": "col_0", "x0": 0, "x1": col_boundary,
                 "y_top": ph, "y_bottom": 0},
                {"id": "col_1", "x0": col_boundary, "x1": pw,
                 "y_top": ph, "y_bottom": 0},
            ]
            return cols, layout_type

    return _single_col(pw, ph), "single_column"


def _single_col(pw: float, ph: float) -> list[dict]:
    return [{"id": "col_0", "x0": 0, "x1": pw, "y_top": ph, "y_bottom": 0}]


def _has_sidebar_body(blks: list[dict]) -> bool:
    """
    Return True if at least one block in this cluster contains real body text
    (not just section headings or tiny icon glyphs).

    A real sidebar has skill items, contact lines, education details, etc.
    A false-positive left cluster caused by narrow section labels + contact
    icons has NO such body content — every block is either a 1-4-word ALL-CAPS
    heading or a tiny symbol/glyph.
    """
    for blk in blks:
        text = blk["text"].strip().split("\n")[0].strip()
        if len(text) < 3:
            continue
        words = text.split()
        alpha_words = [w for w in words if any(c.isalpha() for c in w)]
        if not alpha_words:
            continue
        caps_ratio = sum(1 for w in alpha_words if w.isupper()) / len(alpha_words)
        is_heading_like = caps_ratio >= 0.8 and len(alpha_words) <= 6
        if not is_heading_like and len(text) >= 5:
            return True
    return False


# ---------------------------------------------------------------------------
# Step 7b – Normalize identity placement for sidebar + full-width header layouts
# ---------------------------------------------------------------------------

def _normalize_identity_placement(
    section_map: dict,
    layout_type: str,
    name_blk: dict | None,
    bg_regions: list[dict],
    pw: float,
) -> None:
    """
    For sidebar layouts, if the name sits inside a full-width background band
    (a header that spans both columns), move the identity section from the
    sidebar column to the start of the main column.

    Denny Cheng: name is in the full-width dark header → identity goes to main.
    MVNResume:   name is on the narrow sidebar background → identity stays in sidebar.
    """
    if layout_type not in ("left_sidebar", "right_sidebar") or name_blk is None:
        return

    sidebar_key = "col_0" if layout_type == "left_sidebar" else "col_1"
    main_key    = "col_1" if layout_type == "left_sidebar" else "col_0"
    sidebar_secs = section_map.get(sidebar_key, [])
    main_secs    = section_map.get(main_key, [])

    if not any(s["type"] == "identity" for s in sidebar_secs):
        return  # identity is already in main column or absent

    # Check: is the name block's vertical midpoint inside a full-width region?
    name_cy = (name_blk["bbox"][1] + name_blk["bbox"][3]) / 2
    on_full_width_bg = any(
        reg["width"] > pw * 0.75 and reg["y0"] <= name_cy <= reg["y1"]
        for reg in bg_regions
    )
    if not on_full_width_bg:
        return  # name is on the sidebar background — keep identity in sidebar

    # Move identity to the front of the main column
    section_map[sidebar_key] = [s for s in sidebar_secs if s["type"] != "identity"]
    section_map[main_key]    = [s for s in sidebar_secs if s["type"] == "identity"] + [
        s for s in main_secs if s["type"] != "identity"
    ]


# ---------------------------------------------------------------------------
# Step 4 – Assign block to column
# ---------------------------------------------------------------------------

def _assign_col(bbox: list, columns: list[dict]) -> int:
    cx = (bbox[0] + bbox[2]) / 2
    for i, col in enumerate(columns):
        if col["x0"] <= cx <= col["x1"]:
            return i
    # Fallback: closest column by center
    dists = [abs(cx - (col["x0"] + col["x1"]) / 2) for col in columns]
    return dists.index(min(dists))


# ---------------------------------------------------------------------------
# Step 6 – Identity block detection (name + title)
# ---------------------------------------------------------------------------

def _find_identity(
    blocks: list[dict],
    name_size: float,
    heading_size: float,
    body_size: float,
) -> tuple[dict | None, dict | None]:
    """
    Find the name block and the title/subtitle block.

    Name: largest (or near-largest) font, 1-5 words, not a section keyword.
    Title: adjacent to name, contains a role descriptor.
    """
    section_kw_set = {kw for kw, _ in _SECTION_KEYWORDS}

    def _is_candidate_name(blk: dict) -> bool:
        text = blk["text"].strip()
        words = text.split()

        # Spaced-letter name: "D E N N Y C H E N G"
        # All tokens are single uppercase letters → treat as a single-word name.
        if len(words) >= 2 and all(len(w) == 1 and w.isupper() for w in words):
            return blk["size"] >= name_size * 0.85

        if not (1 <= len(words) <= 5):
            return False
        if text.lower() in section_kw_set:
            return False
        if _match_section_type(text) is not None:
            return False
        if blk["size"] >= name_size * 0.85:
            return True
        return False

    name_blk = None
    for blk in blocks:
        if _is_candidate_name(blk):
            name_blk = blk
            break  # first candidate (largest font, already at top of dominant group)

    if name_blk is None:
        return None, None

    # Title: block within 40pt below or on the same y as name, not a section heading
    ny1 = name_blk["bbox"][3]
    ny0 = name_blk["bbox"][1]
    title_blk = None
    for blk in blocks:
        if blk is name_blk:
            continue
        by0 = blk["bbox"][1]
        text = blk["text"].strip()
        if not text:
            continue
        # Adjacent: overlapping or within 40pt below name
        if by0 >= ny0 - 5 and by0 <= ny1 + 40:
            if _match_section_type(text) is None and len(text.split()) <= 8:
                if blk["size"] >= body_size * 0.9:
                    title_blk = blk
                    break

    return name_blk, title_blk


# ---------------------------------------------------------------------------
# Step 7 – Walk column and label sections
# ---------------------------------------------------------------------------

def _walk_column(
    col_blks: list[dict],
    col_idx: int,
    name_blk: dict | None,
    title_blk: dict | None,
    body_size: float,
    heading_size: float,
    bg_regions: list[dict],
    pw: float,
    element_styles: dict,
) -> tuple[list[dict], dict]:
    """
    Walk blocks top-to-bottom in this column, building sections list and
    populating element_styles.

    Returns (sections, format_flags).
    """
    sections: list[dict] = []
    format_flags: dict[str, str] = {}
    current_section: dict | None = None
    current_type: str | None = None
    has_identity = False

    # Check if name is in this column
    if name_blk and name_blk["col_idx"] == col_idx:
        has_identity = True
        # Record name style
        if "name" not in element_styles:
            element_styles["name"] = _make_style(name_blk, bg_regions)
        if title_blk and title_blk["col_idx"] == col_idx:
            if "subtitle" not in element_styles:
                element_styles["subtitle"] = _make_style(title_blk, bg_regions)

    if has_identity:
        sections.append({"type": "identity"})

    skip_set: set[int] = set()
    if name_blk:
        skip_set.add(id(name_blk))
    if title_blk:
        skip_set.add(id(title_blk))

    for blk in col_blks:
        if id(blk) in skip_set:
            continue
        text = blk["text"].strip()
        if not text:
            continue

        # ── Section heading detection ──────────────────────────────────
        sec_type = _detect_section_heading(blk, body_size, heading_size, bg_regions)
        if sec_type is not None:
            heading_text = text.split("\n")[0].strip()
            # Record section_heading style once
            if "section_heading" not in element_styles:
                style = _make_style(blk, bg_regions)
                # Determine bar height from a thin background rect
                bar_h = _section_bar_height(blk["bbox"], bg_regions)
                style["bar_height"] = bar_h
                if bar_h == 0:
                    style["bg_color"] = None
                element_styles["section_heading"] = style

            current_section = {
                "type": sec_type,
                "heading_text": heading_text,
            }
            current_type = sec_type
            sections.append(current_section)
            continue

        if current_type is None:
            # Above first section heading — body or contact
            _classify_pre_section(blk, bg_regions, element_styles)
            continue

        # ── Classify body blocks within current section ────────────────
        if current_type == "contact":
            if "contact_value" not in element_styles:
                element_styles["contact_value"] = _make_style(blk, bg_regions)

        elif current_type in ("experience", "expertise"):
            flags = _classify_experience_block(blk, element_styles, format_flags)

        elif current_type == "skills":
            _classify_skill_block(blk, element_styles, format_flags)

        elif current_type == "education":
            _classify_education_block(blk, element_styles)

        elif current_type == "summary":
            if "body_paragraph" not in element_styles:
                element_styles["body_paragraph"] = _make_style(blk, bg_regions)

        else:
            # Generic — record as body if not already
            if "body_paragraph" not in element_styles:
                element_styles["body_paragraph"] = _make_style(blk, bg_regions)

    return sections, format_flags


def _classify_pre_section(blk: dict, bg_regions: list[dict], element_styles: dict) -> None:
    """Classify a block that appears before the first section heading."""
    text = blk["text"].strip()
    if _PHONE_RE.search(text) or _EMAIL_RE.search(text) or _URL_RE.search(text):
        if "contact_value" not in element_styles:
            element_styles["contact_value"] = _make_style(blk, bg_regions)


def _classify_experience_block(
    blk: dict, element_styles: dict, format_flags: dict
) -> None:
    """Classify a block within the experience/employment section."""
    text = blk["text"].strip()
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    # Detect inline combined format: "Company · Role   Date · Location"
    has_date = bool(_DATE_RE.search(text))
    has_bullet = text[0] in ("•", "▪", "-", "◦", "●") if text else False

    if has_bullet:
        if "bullet" not in element_styles:
            s = _make_style(blk, element_styles)
            s["bullet_char"] = text[0]
            element_styles["bullet"] = s
        return

    # Check for paragraph-only (no bullets, no dates) → Olivia Wilson style
    if not has_date and not blk["bold"] and len(lines) > 2:
        if "body_paragraph" not in element_styles:
            element_styles["body_paragraph"] = _make_style(blk, element_styles)
        format_flags.setdefault("job_body_format", "paragraph")
        return

    if has_date:
        # Could be company line or a combined line
        # Combined if single-line: "COMPANY · Role   Date"
        if len(lines) == 1 or (len(lines) >= 1 and _DATE_RE.search(lines[0])):
            format_flags.setdefault("job_entry_format", "combined")
            if "job_company" not in element_styles:
                element_styles["job_company"] = _make_style(blk, element_styles)
            if "job_date" not in element_styles:
                s = _make_style(blk, element_styles)
                s["align"] = "right"
                element_styles["job_date"] = s
        else:
            format_flags.setdefault("job_entry_format", "two_line")
            if blk["bold"]:
                if "job_company" not in element_styles:
                    element_styles["job_company"] = _make_style(blk, element_styles)
            else:
                if "job_date" not in element_styles:
                    s = _make_style(blk, element_styles)
                    s["align"] = "right"
                    element_styles["job_date"] = s
    elif blk["bold"]:
        if "job_company" not in element_styles:
            element_styles["job_company"] = _make_style(blk, element_styles)
    elif blk["italic"] or (
        "job_company" in element_styles and not blk["bold"]
    ):
        if "job_role" not in element_styles:
            element_styles["job_role"] = _make_style(blk, element_styles)
    else:
        if "bullet" not in element_styles:
            s = _make_style(blk, element_styles)
            s["bullet_char"] = "•"
            element_styles["bullet"] = s


def _classify_skill_block(
    blk: dict, element_styles: dict, format_flags: dict
) -> None:
    """Classify a block within the skills section."""
    text = blk["text"].strip()
    m = _SKILL_INLINE_RE.match(text.replace("\n", " "))
    if m:
        # Inline format: "CATEGORY: items"
        format_flags.setdefault("skill_format", "inline")
        if "skill_inline" not in element_styles:
            element_styles["skill_inline"] = _make_style(blk, element_styles)
        if "skill_category" not in element_styles:
            s = _make_style(blk, element_styles)
            s["bold"] = True
            element_styles["skill_category"] = s
        if "skill_item" not in element_styles:
            s = _make_style(blk, element_styles)
            s["bold"] = False
            element_styles["skill_item"] = s
        return

    # Heading + items: category is bold/ALL CAPS, items follow
    if blk["bold"] or text.isupper():
        format_flags.setdefault("skill_format", "heading_items")
        if "skill_category" not in element_styles:
            element_styles["skill_category"] = _make_style(blk, element_styles)
    else:
        format_flags.setdefault("skill_format", format_flags.get("skill_format", "flat"))
        if "skill_item" not in element_styles:
            element_styles["skill_item"] = _make_style(blk, element_styles)


def _classify_education_block(blk: dict, element_styles: dict) -> None:
    """Classify a block within the education section."""
    text = blk["text"].strip()
    if _DATE_RE.search(text) and "edu_dates" not in element_styles:
        s = _make_style(blk, element_styles)
        s["align"] = "right"
        element_styles["edu_dates"] = s
    elif blk["bold"] and "edu_school" not in element_styles:
        element_styles["edu_school"] = _make_style(blk, element_styles)
    elif "edu_degree" not in element_styles:
        element_styles["edu_degree"] = _make_style(blk, element_styles)


# ---------------------------------------------------------------------------
# Helpers for block classification
# ---------------------------------------------------------------------------

def _detect_section_heading(
    blk: dict,
    body_size: float,
    heading_size: float,
    bg_regions: list[dict],
) -> str | None:
    """Return canonical section type string or None."""
    text = blk["text"].strip().split("\n")[0].strip()
    if not text:
        return None

    # Must be ALL CAPS (or near-caps — allow digits and punctuation)
    words = text.split()
    if not words:
        return None
    alpha_words = [w for w in words if any(c.isalpha() for c in w)]
    if not alpha_words:
        return None
    caps_ratio = sum(1 for w in alpha_words if w.isupper()) / len(alpha_words)

    is_caps = caps_ratio >= 0.8
    is_large_or_bold = blk["size"] >= heading_size * 0.88 or blk["bold"]
    on_bg = _block_on_bg(blk["bbox"], bg_regions, max_height=50)

    if is_caps:
        sec_type = _match_section_type(text)
        if sec_type is not None:
            # Keyword match always wins — no size/bold requirement
            return sec_type

    if is_caps and (is_large_or_bold or on_bg) and len(words) <= 5:
        # ALL CAPS + visual prominence → custom heading even without keyword
        if on_bg:
            return f"custom_{text.lower().replace(' ', '_')[:30]}"

    return None


def _match_section_type(text: str) -> str | None:
    """Fuzzy keyword match against known section types."""
    tl = text.lower().strip()
    for keyword, sec_type in _SECTION_KEYWORDS:
        if keyword in tl:
            return sec_type
    return None


def _block_on_bg(
    bbox: list,
    bg_regions: list[dict],
    max_height: float = 40.0,
) -> bool:
    """Return True if this bbox overlaps a background region of limited height."""
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    for reg in bg_regions:
        if reg["height"] <= max_height:
            if reg["x0"] <= cx <= reg["x1"] and reg["y0"] <= cy <= reg["y1"]:
                return True
    return False


def _section_bar_height(bbox: list, bg_regions: list[dict]) -> float:
    """Return height of a thin background rect covering this bbox, or 0."""
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    candidates = [
        r for r in bg_regions
        if r["height"] < 40 and r["x0"] <= cx <= r["x1"] and r["y0"] <= cy <= r["y1"]
    ]
    if candidates:
        return min(r["height"] for r in candidates)
    return 0.0


def _make_style(blk: dict, extra: Any = None) -> dict:
    """Extract a JSON-serializable style dict from a block."""
    bg_color: list | None = None
    bar_height = 0.0
    # Note: extra is element_styles dict when called from classify functions,
    # or bg_regions list when called from walk_column — handle both.
    if isinstance(extra, list):
        # bg_regions
        bg_regions = extra
        on_thin = [r for r in bg_regions
                   if r["height"] < 40 and _point_in_rect(
                       ((blk["bbox"][0] + blk["bbox"][2]) / 2,
                        (blk["bbox"][1] + blk["bbox"][3]) / 2), r)]
        if on_thin:
            bar_rect = min(on_thin, key=lambda r: r["height"])
            bg_color = bar_rect["color"]
            bar_height = bar_rect["height"]

    return {
        "font": blk["font"],
        "size": round(blk["size"], 2),
        "color": blk["color"],
        "bold": blk["bold"],
        "italic": blk["italic"],
        "align": blk["align"],
        "leading": round(blk["size"] * 1.35, 2),
        "bg_color": bg_color,
        "bar_height": bar_height,
        "spacing_before": 4.0,
        "spacing_after": 2.0,
        "bullet_char": "",
        "col_idx": blk["col_idx"],
    }


def _point_in_rect(pt: tuple, r: dict) -> bool:
    x, y = pt
    return r["x0"] <= x <= r["x1"] and r["y0"] <= y <= r["y1"]


def _ensure_section_heading_style(element_styles: dict, body_size: float) -> None:
    """Guarantee a section_heading entry exists, deriving from body if needed."""
    if "section_heading" not in element_styles:
        # Fallback: bold, slightly larger than body, no background bar
        element_styles["section_heading"] = {
            "font": "Helvetica-Bold",
            "size": round(body_size * 1.1, 2),
            "color": [0.0, 0.0, 0.0],
            "bold": True,
            "italic": False,
            "align": "left",
            "leading": round(body_size * 1.5, 2),
            "bg_color": None,
            "bar_height": 0.0,
            "spacing_before": 8.0,
            "spacing_after": 4.0,
            "bullet_char": "",
            "col_idx": 0,
        }


# ---------------------------------------------------------------------------
# Step 8 – Spacing values
# ---------------------------------------------------------------------------

def _compute_spacing(blocks: list[dict], body_size: float) -> dict:
    """Measure spacing values from actual block positions."""
    body_spans = [b for b in blocks if abs(b["size"] - body_size) < 2.0 and b["text"].strip()]
    body_spans.sort(key=lambda b: (round(b["bbox"][0] / 50) * 50, b["bbox"][1]))

    # Line spacing: median baseline-to-baseline of consecutive body spans in same column
    line_gaps: list[float] = []
    prev_y1: float | None = None
    prev_col: int = -1
    for b in body_spans:
        col = round(b["bbox"][0] / 50) * 50
        y0 = b["bbox"][1]
        if prev_y1 is not None and col == prev_col:
            gap = y0 - prev_y1
            if 0 < gap < body_size * 2.5:
                line_gaps.append(gap)
        prev_y1 = b["bbox"][3]
        prev_col = col

    line_spacing = (
        statistics.median(line_gaps) + body_size
        if line_gaps else body_size * 1.4
    )

    # Section spacing: large gaps between body spans indicate section breaks
    all_body = sorted(body_spans, key=lambda b: b["bbox"][1])
    sec_gaps: list[float] = []
    for i in range(1, len(all_body)):
        gap = all_body[i]["bbox"][1] - all_body[i - 1]["bbox"][3]
        if gap > body_size * 1.5:
            sec_gaps.append(gap)
    section_spacing = max(4.0, min(24.0, statistics.median(sec_gaps) if sec_gaps else 8.0))

    # Bullet indent: x offset of bullet/indented lines vs. section left margin
    bullet_blocks = [
        b for b in blocks
        if b["text"].strip() and b["text"].strip()[0] in ("•", "▪", "-", "◦", "●")
    ]
    if bullet_blocks:
        non_bullet_x = [
            b["bbox"][0] for b in body_spans
            if b["text"].strip() and b["text"].strip()[0] not in ("•", "▪", "-", "◦", "●")
        ]
        bullet_x = [b["bbox"][0] for b in bullet_blocks]
        if non_bullet_x and bullet_x:
            bullet_indent = max(0.0, statistics.median(bullet_x) - statistics.median(non_bullet_x))
        else:
            bullet_indent = 10.0
    else:
        bullet_indent = 10.0

    return {
        "line_spacing": round(line_spacing, 2),
        "section_spacing": round(section_spacing, 2),
        "entry_spacing": round(section_spacing * 0.6, 2),
        "bullet_indent": round(bullet_indent, 2),
    }


# ---------------------------------------------------------------------------
# Color utility
# ---------------------------------------------------------------------------

def _int_to_rgb(val: int | float | list | tuple) -> list[float]:
    """Convert PyMuPDF color (packed int or tuple) to [r, g, b] list 0-1."""
    if isinstance(val, (list, tuple)) and len(val) >= 3:
        vals = [float(v) for v in val[:3]]
        if any(v > 1.0 for v in vals):
            return [v / 255 for v in vals]
        return vals
    if isinstance(val, (int, float)):
        vi = int(val)
        r = (vi >> 16) & 0xFF
        g = (vi >> 8) & 0xFF
        b = vi & 0xFF
        return [r / 255.0, g / 255.0, b / 255.0]
    return [0.0, 0.0, 0.0]
