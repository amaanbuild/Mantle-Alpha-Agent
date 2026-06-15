"""Alert-rule CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.alerts.service import AlertService, AlertServiceError
from backend.api.dependencies import db_session, require_api_key
from backend.api.schemas import (
    AlertRuleResponse,
    CreateAlertRequest,
    MessageResponse,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertRuleResponse], summary="List alert rules")
async def list_alerts(
    telegram_id: int = Query(..., description="Owner's Telegram id."),
    session: AsyncSession = Depends(db_session),
) -> list[AlertRuleResponse]:
    service = AlertService(session)
    user = await service.users.get_by_telegram_id(telegram_id)
    if user is None:
        return []
    rules = await service.list_rules(user)
    return [AlertRuleResponse.model_validate(r) for r in rules]


@router.post(
    "",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an alert rule",
    dependencies=[Depends(require_api_key)],
)
async def create_alert(
    payload: CreateAlertRequest,
    session: AsyncSession = Depends(db_session),
) -> AlertRuleResponse:
    service = AlertService(session)
    user = await service.users.get_or_create(
        telegram_id=payload.telegram_id,
        chat_id=payload.chat_id or payload.telegram_id,
    )
    try:
        rule = await service.create_rule(
            user=user,
            token=payload.token,
            threshold_usd=payload.threshold_usd,
            event_type=payload.event_type,
            raw_request="api",
        )
    except (AlertServiceError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AlertRuleResponse.model_validate(rule)


@router.delete(
    "/{rule_id}",
    response_model=MessageResponse,
    summary="Delete (deactivate) an alert rule",
    dependencies=[Depends(require_api_key)],
)
async def delete_alert(
    rule_id: int,
    telegram_id: int = Query(..., description="Owner's Telegram id."),
    session: AsyncSession = Depends(db_session),
) -> MessageResponse:
    service = AlertService(session)
    user = await service.users.get_by_telegram_id(telegram_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    ok = await service.delete_rule(user, rule_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")
    return MessageResponse(message=f"Rule {rule_id} deactivated.")
