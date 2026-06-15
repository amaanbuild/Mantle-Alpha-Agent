"""
FastAPI dependencies: DB session, optional API-key auth, alert service.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.alerts.service import AlertService
from backend.config import settings
from backend.database.session import get_session


async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped DB session that auto-commits on success."""
    async for session in get_session():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_alert_service(
    session: AsyncSession = Depends(db_session),
) -> AlertService:
    return AlertService(session)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Enforce the optional API key on mutating endpoints (no-op if unset)."""
    if not settings.API_KEY:
        return
    if x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key."
        )
