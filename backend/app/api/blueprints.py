"""Blueprint read/update/re-extract endpoints."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_store
from app.models.blueprint import BackgroundRegion, Blueprint, Column, ElementStyle, Section
from app.services.extractor import extract_blueprint
from app.storage.template_store import TemplateStore

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/blueprints", tags=["blueprints"])

Store = Annotated[TemplateStore, Depends(get_store)]


class BlueprintUpdate(BaseModel):
    """Partial blueprint update. Supplied top-level fields replace their existing values."""

    page_width: float | None = None
    page_height: float | None = None
    layout_type: str | None = None
    background_regions: list[BackgroundRegion] | None = None
    columns: list[Column] | None = None
    element_styles: dict[str, ElementStyle] | None = None
    section_map: dict[str, list[Section]] | None = None
    skill_format: str | None = None
    job_entry_format: str | None = None
    job_body_format: str | None = None
    line_spacing: float | None = None
    section_spacing: float | None = None
    entry_spacing: float | None = None
    bullet_indent: float | None = None


@router.get("/{template_id}", response_model=Blueprint)
async def get_blueprint(store: Store, template_id: str) -> Blueprint:
    try:
        store.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    try:
        return store.get_blueprint(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{template_id}", response_model=Blueprint)
async def update_blueprint(
    store: Store,
    template_id: str,
    update: BlueprintUpdate,
) -> Blueprint:
    try:
        store.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    try:
        existing = store.get_blueprint(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    changes = update.model_dump(exclude_unset=True)
    merged = existing.model_copy(update=changes)
    store.save_blueprint(template_id, merged)
    logger.info("blueprint_updated", template_id=template_id, fields=list(changes))
    return merged


@router.post("/{template_id}/extract", response_model=Blueprint)
async def reextract_blueprint(store: Store, template_id: str) -> Blueprint:
    try:
        store.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    try:
        pdf_path = store.get_source_pdf_path(template_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    blueprint = extract_blueprint(pdf_path)
    store.save_blueprint(template_id, blueprint)
    logger.info("blueprint_reextracted", template_id=template_id)
    return blueprint
