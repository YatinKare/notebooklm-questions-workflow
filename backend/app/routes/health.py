from fastapi import APIRouter

from .. import db
from ..notebooklm.client import get_notebooklm_client

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    db_ok = await db.health_check()
    try:
        mcp_ok = await get_notebooklm_client().health_check()
    except RuntimeError:
        mcp_ok = False
    healthy = db_ok and mcp_ok
    return {
        "status": "ok" if healthy else "degraded",
        "db": "ok" if db_ok else "error",
        "mcp": "ok" if mcp_ok else "error",
    }
