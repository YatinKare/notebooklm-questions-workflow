from fastapi import APIRouter, HTTPException, UploadFile

from .. import db
from ..models import Upload, UploadSummary

router = APIRouter()


@router.post("/uploads")
async def create_upload(file: UploadFile) -> dict[str, str]:
    # Full implementation lands in §2.4 / §2.8 (enqueue + pipeline).
    raise HTTPException(status_code=501, detail="not implemented yet")


@router.get("/uploads")
async def list_uploads() -> list[UploadSummary]:
    return await db.list_uploads()


@router.get("/uploads/{job_id}")
async def get_upload(job_id: str) -> Upload:
    upload = await db.get_upload_full(job_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return upload
