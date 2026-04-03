"""Template CRUD endpoints: upload, list, get, delete."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form

from app.api.deps import get_store, get_template_service
from app.models.template import TemplateDetail, TemplateMeta
from app.services.template_service import TemplateService
from app.storage.template_store import TemplateStore

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/templates", tags=["templates"])

Store = Annotated[TemplateStore, Depends(get_store)]
Service = Annotated[TemplateService, Depends(get_template_service)]


@router.post("", status_code=201, response_model=TemplateMeta)
async def upload_template(
    service: Service,
    file: UploadFile,
    name: Annotated[str | None, Form()] = None,
) -> TemplateMeta:
    try:
        return await service.upload_template(file, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[TemplateMeta])
async def list_templates(store: Store) -> list[TemplateMeta]:
    return store.list_templates()


@router.get("/{template_id}", response_model=TemplateDetail)
async def get_template(service: Service, template_id: str) -> TemplateDetail:
    try:
        return service.get_detail(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc


@router.delete("/{template_id}", status_code=204)
async def delete_template(store: Store, template_id: str) -> None:
    try:
        store.delete_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
