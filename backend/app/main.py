from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api import api_router
from app.api.deps import set_store
from app.config import get_settings
from app.storage import CorruptedMetadataError, TemplateStore

logger = structlog.stdlib.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.templates_dir.mkdir(parents=True, exist_ok=True)

    store = TemplateStore(settings.templates_dir)
    set_store(store)
    logger.info("startup", data_dir=str(settings.data_dir), templates=len(store.list_templates()))

    yield

    logger.info("shutdown")


app = FastAPI(
    title="Resume Style Builder",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


@app.exception_handler(CorruptedMetadataError)
async def corrupted_metadata_handler(request: Request, exc: CorruptedMetadataError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Template metadata is corrupted. Contact the administrator."})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
