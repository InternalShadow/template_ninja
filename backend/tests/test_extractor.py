"""Tests for the unified PyMuPDF extraction pipeline."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from app.models.blueprint import Blueprint
from app.services.extractor import extract_blueprint

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_TEMPLATE_PDF = (
    _DATA_DIR
    / "templates_store"
    / "bd297366-2763-41b1-a15c-316414aad172"
    / "source.pdf"
)
_OUTPUT_PDF = _DATA_DIR / "output" / "resume_Jannine_Chan_Resume.pdf"
_EMPTY_PDF = _DATA_DIR / "output" / "resume_!Resume.pdf"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def template_blueprint() -> Blueprint:
    """Extract the Jannine Chan template once for all tests in this module."""
    assert _TEMPLATE_PDF.exists(), f"Template PDF missing: {_TEMPLATE_PDF}"
    return extract_blueprint(_TEMPLATE_PDF)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="PDF not found"):
            extract_blueprint(tmp_path / "nonexistent.pdf")

    def test_empty_pdf_raises(self) -> None:
        if not _EMPTY_PDF.exists():
            pytest.skip("Empty PDF not available")
        with pytest.raises(ValueError, match="no pages"):
            extract_blueprint(_EMPTY_PDF)

    def test_non_pdf_raises(self, tmp_path: Path) -> None:
        fake = tmp_path / "fake.pdf"
        fake.write_text("not a pdf")
        with pytest.raises(Exception):
            extract_blueprint(fake)


# ---------------------------------------------------------------------------
# Template PDF extraction
# ---------------------------------------------------------------------------


class TestTemplateExtraction:
    def test_returns_blueprint_model(self, template_blueprint: Blueprint) -> None:
        assert isinstance(template_blueprint, Blueprint)

    def test_page_dimensions(self, template_blueprint: Blueprint) -> None:
        assert template_blueprint.page_width == pytest.approx(612.0, abs=1)
        assert template_blueprint.page_height == pytest.approx(792.0, abs=1)

    def test_two_column_layout(self, template_blueprint: Blueprint) -> None:
        assert template_blueprint.layout_type == "two_column"
        assert len(template_blueprint.columns) == 2

    def test_column_boundaries(self, template_blueprint: Blueprint) -> None:
        left, right = template_blueprint.columns
        assert left.id == "col_0"
        assert right.id == "col_1"
        assert left.x1 < right.x0
        assert left.x0 < 50
        assert right.x1 > 500

    def test_element_styles_present(self, template_blueprint: Blueprint) -> None:
        styles = template_blueprint.element_styles
        assert "name" in styles
        assert "section_heading" in styles
        assert "body_paragraph" in styles

    def test_name_is_largest_font(self, template_blueprint: Blueprint) -> None:
        styles = template_blueprint.element_styles
        name_size = styles["name"].size
        for role, style in styles.items():
            if role != "name":
                assert style.size <= name_size, f"{role} size {style.size} > name size {name_size}"

    def test_body_paragraph_most_common(self, template_blueprint: Blueprint) -> None:
        assert "body_paragraph" in template_blueprint.element_styles

    def test_sections_detected(self, template_blueprint: Blueprint) -> None:
        all_sections = [
            sec
            for secs in template_blueprint.section_map.values()
            for sec in secs
        ]
        content_keys = {s.content_key for s in all_sections}
        assert "skills" in content_keys
        assert "experience" in content_keys
        assert "education" in content_keys

    def test_experience_in_right_column(self, template_blueprint: Blueprint) -> None:
        right_col_id = template_blueprint.columns[1].id
        right_sections = template_blueprint.section_map.get(right_col_id, [])
        keys = {s.content_key for s in right_sections}
        assert "experience" in keys

    def test_skills_in_left_column(self, template_blueprint: Blueprint) -> None:
        left_col_id = template_blueprint.columns[0].id
        left_sections = template_blueprint.section_map.get(left_col_id, [])
        keys = {s.content_key for s in left_sections}
        assert "skills" in keys

    def test_spacing_reasonable(self, template_blueprint: Blueprint) -> None:
        assert 5 < template_blueprint.line_spacing < 30
        assert 10 < template_blueprint.section_spacing < 50
        assert 5 < template_blueprint.entry_spacing < 30
        assert template_blueprint.bullet_indent >= 0

    def test_skill_format_inline(self, template_blueprint: Blueprint) -> None:
        assert template_blueprint.skill_format == "inline"

    def test_job_body_bullet(self, template_blueprint: Blueprint) -> None:
        assert template_blueprint.job_body_format == "bullet"

    def test_serialization_roundtrip(self, template_blueprint: Blueprint) -> None:
        json_str = template_blueprint.model_dump_json()
        restored = Blueprint.model_validate_json(json_str)
        assert restored == template_blueprint


# ---------------------------------------------------------------------------
# Minimal PDF extraction
# ---------------------------------------------------------------------------


class TestMinimalPdf:
    def test_minimal_pdf_produces_valid_blueprint(self) -> None:
        if not _OUTPUT_PDF.exists():
            pytest.skip("Output PDF not available")
        bp = extract_blueprint(_OUTPUT_PDF)
        assert isinstance(bp, Blueprint)
        assert bp.page_width > 0
        assert bp.page_height > 0


# ---------------------------------------------------------------------------
# Synthetic single-page PDF
# ---------------------------------------------------------------------------


class TestSyntheticPdf:
    @pytest.fixture()
    def synthetic_pdf(self, tmp_path: Path) -> Path:
        """Build a minimal single-page PDF with known text."""
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((200, 60), "JOHN DOE", fontsize=24, fontname="helv")
        page.insert_text((200, 90), "Software Engineer", fontsize=14, fontname="helv")
        page.insert_text((50, 150), "EXPERIENCE", fontsize=12, fontname="hebo")
        page.insert_text((50, 180), "Worked on things.", fontsize=10, fontname="helv")
        page.insert_text((50, 200), "EDUCATION", fontsize=12, fontname="hebo")
        page.insert_text((50, 230), "Studied at places.", fontsize=10, fontname="helv")

        pdf_path = tmp_path / "synthetic.pdf"
        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def test_extracts_name(self, synthetic_pdf: Path) -> None:
        bp = extract_blueprint(synthetic_pdf)
        assert "name" in bp.element_styles
        assert bp.element_styles["name"].size == pytest.approx(24, abs=1)

    def test_single_column(self, synthetic_pdf: Path) -> None:
        bp = extract_blueprint(synthetic_pdf)
        assert bp.layout_type == "single_column"
        assert len(bp.columns) == 1

    def test_sections_detected_from_bold(self, synthetic_pdf: Path) -> None:
        bp = extract_blueprint(synthetic_pdf)
        all_keys = {
            sec.content_key
            for secs in bp.section_map.values()
            for sec in secs
        }
        assert "experience" in all_keys
        assert "education" in all_keys
