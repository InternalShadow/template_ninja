"""Shared FastAPI dependencies for API routes."""

from app.services.template_service import TemplateService
from app.storage.template_store import TemplateStore

_store: TemplateStore | None = None


def set_store(store: TemplateStore) -> None:
    global _store
    _store = store


def get_store() -> TemplateStore:
    if _store is None:
        raise RuntimeError("TemplateStore not initialized — lifespan has not run")
    return _store


def get_template_service() -> TemplateService:
    return TemplateService(get_store())
