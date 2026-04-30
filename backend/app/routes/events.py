from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/events/{job_id}")
async def events(job_id: str):  # noqa: ANN201 — full impl in §2.7
    raise HTTPException(status_code=501, detail="not implemented yet")
