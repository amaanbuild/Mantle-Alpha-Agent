"""Health & readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from backend import __version__
from backend.api.schemas import HealthResponse
from backend.blockchain.client import get_mantle_client
from backend.config import settings
from backend.database.session import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness & dependency health")
async def health() -> HealthResponse:
    """Report service health plus database and RPC connectivity."""
    db_ok = await _check_db()
    rpc_ok = await get_mantle_client().is_connected()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        app=settings.APP_NAME,
        version=__version__,
        environment=settings.ENVIRONMENT,
        database=db_ok,
        rpc=rpc_ok,
    )


async def _check_db() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
