from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from .. import db
from ..models import Upload, UploadSummary
from ..pipeline.orchestrator import get_orchestrator

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000


@router.post("/uploads")
async def create_upload(file: UploadFile = File(...)) -> dict[str, str]:
    image_bytes = await _read_and_validate_image(file)
    upload_id = await db.create_upload()
    await get_orchestrator().enqueue(upload_id, image_bytes)
    return {"job_id": upload_id}


@router.get("/uploads")
async def list_uploads() -> list[UploadSummary]:
    return await db.list_uploads()


@router.get("/uploads/{job_id}")
async def get_upload(job_id: str) -> Upload:
    upload = await db.get_upload_full(job_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return upload


async def _read_and_validate_image(file: UploadFile) -> bytes:
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="file must be an image")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="image is too large")

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=415, detail="file must be a valid image") from exc

    if width <= 0 or height <= 0:
        raise HTTPException(status_code=415, detail="file must be a valid image")
    if width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=413, detail="image dimensions are too large")
    return data
