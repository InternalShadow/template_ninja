from datetime import datetime

from pydantic import BaseModel

from app.models.blueprint import Blueprint


class TemplateMeta(BaseModel):
    """Lightweight metadata for a stored template."""

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    has_source: bool = False
    has_blueprint: bool = False


class TemplateDetail(TemplateMeta):
    """Template metadata plus its full blueprint."""

    blueprint: Blueprint | None = None
