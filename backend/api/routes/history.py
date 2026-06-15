"""Alert-history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.alerts.service import AlertService
from backend.api.dependencies import db_session
from backend.api.schemas import AlertHistoryResponse
from backend.database.repositories import AlertHistoryRepository

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[AlertHistoryResponse], summary="Recent alert history")
async def get_history(
    telegram_id: int | None = Query(
        default=None, description="Filter to a single user's history (optional)."
    ),
    limit: int = Query(default=20, ge=1, le=100),
    today_only: bool = Query(default=False),
    session: AsyncSession = Depends(db_session),
) -> list[AlertHistoryResponse]:
    if telegram_id is not None:
        service = AlertService(session)
        user = await service.users.get_by_telegram_id(telegram_id)
        if user is None:
            return []
        alerts = await service.recent_history(user, limit=limit, today_only=today_only)
    else:
        alerts = await AlertHistoryRepository(session).list_recent(limit=limit)
    return [AlertHistoryResponse.model_validate(a) for a in alerts]
