"""Generation endpoints: produce PDF and PNG preview from ResumeContent."""

from typing import Annotated

import fitz
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import get_store
from app.models.content import ResumeContent
from app.services.generator import generate_pdf
from app.storage.template_store import TemplateStore

logger = structlog.stdlib.get_logger()

router = APIRouter(tags=["generation"])

Store = Annotated[TemplateStore, Depends(get_store)]


@router.post("/generate/{template_id}", response_class=Response)
async def generate(store: Store, template_id: str, content: ResumeContent) -> Response:
    """Generate a PDF from user-supplied resume content and return raw PDF bytes."""
    try:
        store.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc

    pdf_bytes = generate_pdf(content)
    logger.info("pdf_generated", template_id=template_id, size_bytes=len(pdf_bytes))
    return Response(content=pdf_bytes, media_type="application/pdf")


@router.post("/preview/{template_id}", response_class=Response)
async def preview(store: Store, template_id: str, content: ResumeContent) -> Response:
    """Generate a PDF, render page 0 to PNG, and return the image bytes."""
    try:
        store.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc

    pdf_bytes = generate_pdf(content)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        png_bytes = pixmap.tobytes(output="png")
    finally:
        doc.close()

    logger.info("preview_generated", template_id=template_id, size_bytes=len(png_bytes))
    return Response(content=png_bytes, media_type="image/png")
