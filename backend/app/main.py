from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.storage import TemplateStore

logger = structlog.stdlib.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict]:
    settings = get_settings()
    settings.templates_dir.mkdir(parents=True, exist_ok=True)

    store = TemplateStore(settings.templates_dir)
    logger.info("startup", data_dir=str(settings.data_dir), templates=len(store.list_templates()))

    yield {"store": store}

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
