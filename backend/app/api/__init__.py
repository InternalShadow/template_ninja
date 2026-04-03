from fastapi import APIRouter

from app.api.blueprints import router as blueprints_router
from app.api.templates import router as templates_router

api_router = APIRouter()
api_router.include_router(templates_router)
api_router.include_router(blueprints_router)

__all__ = ["api_router"]
