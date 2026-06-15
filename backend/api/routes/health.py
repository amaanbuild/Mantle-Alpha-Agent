"""Health & readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response
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


@router.head("/health", include_in_schema=False)
async def health_head() -> Response:
    """Lightweight liveness for uptime pingers that send HEAD (e.g. UptimeRobot).

    Returns 200 immediately without the DB/RPC checks, so a keep-alive ping is
    cheap and never reports the service as down on method mismatch.
    """
    return Response(status_code=200)


async def _check_db() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
