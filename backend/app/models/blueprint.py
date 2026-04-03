from pydantic import BaseModel


class Column(BaseModel):
    """A vertical region in the page layout."""

    id: str
    x0: float
    x1: float
    y_top: float
    y_bottom: float


class BackgroundRegion(BaseModel):
    """A filled rectangle drawn behind content."""

    x0: float
    y0: float
    x1: float
    y1: float
    color: tuple[float, float, float]
    opacity: float = 1.0


class ElementStyle(BaseModel):
    """Visual style for a semantic text role (name, section heading, body, etc.)."""

    font: str
    size: float
    color: tuple[float, float, float]
    bold: bool = False
    italic: bool = False
    align: str = "left"
    leading: float = 0.0
    bg_color: tuple[float, float, float] | None = None
    bar_height: float = 0.0
    spacing_before: float = 0.0
    spacing_after: float = 0.0
    bullet_char: str = ""
    col_idx: int = 0


class Section(BaseModel):
    """A named resume section placed within a column."""

    label: str
    content_key: str


class Blueprint(BaseModel):
    """Complete visual blueprint extracted from a template PDF."""

    page_width: float = 612.0
    page_height: float = 792.0
    layout_type: str = "single_column"
    background_regions: list[BackgroundRegion] = []
    columns: list[Column] = []
    element_styles: dict[str, ElementStyle] = {}
    section_map: dict[str, list[Section]] = {}
    skill_format: str = "inline"
    job_entry_format: str = "two_line"
    job_body_format: str = "bullet"
    line_spacing: float = 14.0
    section_spacing: float = 24.0
    entry_spacing: float = 14.0
    bullet_indent: float = 10.0
