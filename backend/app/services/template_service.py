"""Upload orchestration: validate file, save PDF, extract blueprint, update metadata."""

from pathlib import Path

import structlog
from fastapi import UploadFile

from app.config import get_settings
from app.models.blueprint import Blueprint
from app.models.template import TemplateDetail, TemplateMeta
from app.services.extractor import extract_blueprint
from app.storage.template_store import TemplateStore

logger = structlog.stdlib.get_logger()


class TemplateService:
    """Coordinates the full upload-and-extract workflow."""

    def __init__(self, store: TemplateStore) -> None:
        self._store = store

    async def upload_template(
        self,
        file: UploadFile,
        name: str | None = None,
    ) -> TemplateMeta:
        """Save an uploaded PDF, extract its blueprint, and return metadata.

        Raises ValueError for invalid files and propagates extraction errors.
        """
        settings = get_settings()
        self._validate_upload(file, settings.allowed_extensions, settings.upload_max_size_mb)

        data = await file.read()
        max_bytes = settings.upload_max_size_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise ValueError(f"File exceeds maximum size of {settings.upload_max_size_mb} MB")

        display_name = name or Path(file.filename or "Untitled").stem

        meta = self._store.create_template(display_name)
        template_id = meta.id

        try:
            pdf_path = self._store.save_source_pdf(template_id, data)
            blueprint = extract_blueprint(pdf_path)
            self._store.save_blueprint(template_id, blueprint)
        except Exception:
            logger.exception("upload_failed", template_id=template_id)
            self._store.delete_template(template_id)
            raise

        return self._store.get_template(template_id)

    def get_detail(self, template_id: str) -> TemplateDetail:
        """Return full template detail (meta + blueprint) for a given ID."""
        meta = self._store.get_template(template_id)
        blueprint: Blueprint | None = None
        try:
            blueprint = self._store.get_blueprint(template_id)
        except FileNotFoundError:
            pass

        return TemplateDetail(
            **meta.model_dump(),
            blueprint=blueprint,
        )

    @staticmethod
    def _validate_upload(
        file: UploadFile,
        allowed_extensions: frozenset[str],
        max_size_mb: int,
    ) -> None:
        filename = file.filename or ""
        ext = Path(filename).suffix.lower()
        if ext not in allowed_extensions:
            raise ValueError(
                f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed_extensions))}"
            )

        if file.size is not None and file.size > max_size_mb * 1024 * 1024:
            raise ValueError(f"File exceeds maximum size of {max_size_mb} MB")
