import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.models.blueprint import Blueprint
from app.models.template import TemplateMeta

logger = structlog.stdlib.get_logger()


class CorruptedMetadataError(Exception):
    """Raised when templates_metadata.json exists but cannot be parsed."""

    def __init__(self, path: Path, cause: Exception) -> None:
        self.path = path
        super().__init__(f"Corrupted metadata file at {path}: {cause}")


class TemplateStore:
    """Filesystem-backed CRUD for templates, blueprints, and source PDFs."""

    def __init__(self, templates_dir: Path) -> None:
        self._root = templates_dir
        self._metadata_path = templates_dir / "templates_metadata.json"
        self._root.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> dict[str, TemplateMeta]:
        if not self._metadata_path.exists():
            return {}
        text = self._metadata_path.read_text(encoding="utf-8")
        try:
            raw: dict = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error("metadata_corrupted", path=str(self._metadata_path), error=str(exc))
            raise CorruptedMetadataError(self._metadata_path, exc) from exc
        return {k: TemplateMeta.model_validate(v) for k, v in raw.items()}

    def _save_index(self, index: dict[str, TemplateMeta]) -> None:
        data = {k: v.model_dump(mode="json") for k, v in index.items()}
        self._metadata_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_templates(self) -> list[TemplateMeta]:
        templates = list(self._load_index().values())
        templates.sort(key=lambda t: t.updated_at, reverse=True)
        return templates

    def get_template(self, template_id: str) -> TemplateMeta:
        index = self._load_index()
        if template_id not in index:
            raise KeyError(f"Template '{template_id}' not found")
        return index[template_id]

    def create_template(self, name: str, template_id: str | None = None) -> TemplateMeta:
        tid = template_id or str(uuid.uuid4())
        template_dir = self._root / tid
        template_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(tz=UTC)
        meta = TemplateMeta(id=tid, name=name, created_at=now, updated_at=now)

        index = self._load_index()
        index[tid] = meta
        self._save_index(index)
        logger.info("template_created", template_id=tid, name=name)
        return meta

    def delete_template(self, template_id: str) -> None:
        index = self._load_index()
        if template_id not in index:
            raise KeyError(f"Template '{template_id}' not found")

        template_dir = self._root / template_id
        if template_dir.exists():
            shutil.rmtree(template_dir)

        del index[template_id]
        self._save_index(index)
        logger.info("template_deleted", template_id=template_id)

    def get_blueprint(self, template_id: str) -> Blueprint:
        bp_path = self._root / template_id / "blueprint.json"
        if not bp_path.exists():
            raise FileNotFoundError(f"Blueprint not found for template '{template_id}'")
        return Blueprint.model_validate_json(bp_path.read_text(encoding="utf-8"))

    def save_blueprint(self, template_id: str, blueprint: Blueprint) -> None:
        self.get_template(template_id)
        bp_path = self._root / template_id / "blueprint.json"
        bp_path.write_text(blueprint.model_dump_json(indent=2), encoding="utf-8")
        self._update_meta(template_id, has_blueprint=True)
        logger.info("blueprint_saved", template_id=template_id)

    def save_source_pdf(self, template_id: str, data: bytes) -> Path:
        self.get_template(template_id)
        pdf_path = self._root / template_id / "source.pdf"
        pdf_path.write_bytes(data)
        self._update_meta(template_id, has_source=True)
        logger.info("source_pdf_saved", template_id=template_id, size_bytes=len(data))
        return pdf_path

    def get_source_pdf_path(self, template_id: str) -> Path:
        pdf_path = self._root / template_id / "source.pdf"
        if not pdf_path.exists():
            raise FileNotFoundError(f"Source PDF not found for template '{template_id}'")
        return pdf_path

    def get_template_dir(self, template_id: str) -> Path:
        """Return the on-disk directory for *template_id*.

        Raises ``KeyError`` if the template is not in the metadata index.
        """
        self.get_template(template_id)
        return self._root / template_id

    def _update_meta(
        self,
        template_id: str,
        *,
        has_source: bool | None = None,
        has_blueprint: bool | None = None,
    ) -> None:
        index = self._load_index()
        if template_id not in index:
            raise KeyError(f"Template '{template_id}' not found")

        meta = index[template_id]
        updates: dict[str, object] = {"updated_at": datetime.now(tz=UTC)}
        if has_source is not None:
            updates["has_source"] = has_source
        if has_blueprint is not None:
            updates["has_blueprint"] = has_blueprint

        index[template_id] = meta.model_copy(update=updates)
        self._save_index(index)
