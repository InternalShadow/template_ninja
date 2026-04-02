"""
Template Storage - Manages storage and retrieval of resume templates.

Each template lives in its own directory under *storage_dir* and contains:
  source.pdf      - the original uploaded template (optional)
  styles.json     - legacy thin-theme styles (kept for backward compatibility)
  blueprint.json  - the rich TemplateBlueprint produced by the extractor
"""
from __future__ import annotations

import json
import os
import uuid
import shutil
from datetime import datetime


class TemplateStorage:
    """Manages storage and retrieval of resume templates."""

    def __init__(self, storage_dir: str = "templates_store") -> None:
        self.storage_dir = storage_dir
        self.metadata_file = os.path.join(storage_dir, "templates_metadata.json")
        self._ensure_storage_exists()
        self._load_metadata()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_storage_exists(self) -> None:
        os.makedirs(self.storage_dir, exist_ok=True)
        if not os.path.exists(self.metadata_file):
            self._save_metadata({})

    def _load_metadata(self) -> None:
        try:
            with open(self.metadata_file, "r") as f:
                self.metadata: dict = json.load(f)
        except Exception:
            self.metadata = {}

    def _save_metadata(self, metadata: dict | None = None) -> None:
        if metadata is None:
            metadata = self.metadata
        with open(self.metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

    def _template_dir(self, template_id: str) -> str:
        return os.path.join(self.storage_dir, template_id)

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def save_template(
        self,
        name: str,
        styles: dict,
        source_file: str | None = None,
        blueprint: dict | None = None,
    ) -> str:
        """Save a new template; return the new template_id."""
        template_id = str(uuid.uuid4())
        template_dir = self._template_dir(template_id)
        os.makedirs(template_dir, exist_ok=True)

        # Legacy styles
        with open(os.path.join(template_dir, "styles.json"), "w") as f:
            json.dump(styles, f, indent=2)

        # Blueprint (may be None on first upload before extraction)
        if blueprint is not None:
            with open(os.path.join(template_dir, "blueprint.json"), "w") as f:
                json.dump(blueprint, f, indent=2)

        # Source PDF
        if source_file and os.path.exists(source_file):
            ext = os.path.splitext(source_file)[1]
            shutil.copy2(source_file, os.path.join(template_dir, f"source{ext}"))

        self.metadata[template_id] = {
            "id": template_id,
            "name": name,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "has_source": source_file is not None,
            "has_blueprint": blueprint is not None,
        }
        self._save_metadata()
        return template_id

    def get_template(self, template_id: str) -> dict | None:
        """Return template info including styles (and blueprint if available)."""
        if template_id not in self.metadata:
            return None

        info = self.metadata[template_id]
        template_dir = self._template_dir(template_id)
        styles_file = os.path.join(template_dir, "styles.json")

        if not os.path.exists(styles_file):
            return None

        with open(styles_file, "r") as f:
            styles = json.load(f)

        result: dict = {
            "id": template_id,
            "name": info["name"],
            "created_at": info["created_at"],
            "updated_at": info["updated_at"],
            "styles": styles,
            "has_source": info.get("has_source", False),
            "has_blueprint": info.get("has_blueprint", False),
        }

        # Attach blueprint if it exists
        bp = self.get_blueprint(template_id)
        if bp is not None:
            result["blueprint"] = bp

        return result

    def list_templates(self) -> list[dict]:
        """Return summary info for all stored templates, newest first."""
        templates = [
            {
                "id": tid,
                "name": info["name"],
                "created_at": info["created_at"],
                "updated_at": info["updated_at"],
                "has_source": info.get("has_source", False),
                "has_blueprint": info.get("has_blueprint", False),
            }
            for tid, info in self.metadata.items()
        ]
        templates.sort(key=lambda x: x["created_at"], reverse=True)
        return templates

    def delete_template(self, template_id: str) -> bool:
        """Delete a template and all its files."""
        if template_id not in self.metadata:
            return False

        template_dir = self._template_dir(template_id)
        if os.path.exists(template_dir):
            shutil.rmtree(template_dir)

        del self.metadata[template_id]
        self._save_metadata()
        return True

    # ------------------------------------------------------------------
    # Blueprint-specific accessors
    # ------------------------------------------------------------------

    def save_blueprint(self, template_id: str, blueprint: dict) -> bool:
        """Persist *blueprint* as blueprint.json for the given template."""
        template_dir = self._template_dir(template_id)
        if not os.path.exists(template_dir):
            return False
        with open(os.path.join(template_dir, "blueprint.json"), "w") as f:
            json.dump(blueprint, f, indent=2)
        if template_id in self.metadata:
            self.metadata[template_id]["has_blueprint"] = True
            self.metadata[template_id]["updated_at"] = datetime.now().isoformat()
            self._save_metadata()
        return True

    def get_blueprint(self, template_id: str) -> dict | None:
        """Load and return blueprint.json, or None if it does not exist."""
        bp_file = os.path.join(self._template_dir(template_id), "blueprint.json")
        if not os.path.exists(bp_file):
            return None
        with open(bp_file, "r") as f:
            return json.load(f)

