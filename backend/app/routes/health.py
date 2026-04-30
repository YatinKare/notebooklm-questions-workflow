from fastapi import APIRouter

from ..notebooklm.client import get_notebooklm_client

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    mcp_ok = await get_notebooklm_client().health_check()
    return {"status": "ok" if mcp_ok else "degraded", "mcp": "ok" if mcp_ok else "error"}
