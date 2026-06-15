"""
Alert service: user-facing rule management.

The single backend used by BOTH the Telegram bot and the REST API, so slash
commands and natural language share identical behavior. Methods take an
:class:`AsyncSession` (caller owns the transaction) and operate through the
repository layer. Domain/validation errors raise :class:`AlertServiceError`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.core.domain import ExtractedIntent
from backend.core.security import validate_threshold, validate_token_symbol
from backend.core.types import EventType, IntentType, resolve_token
from backend.database.models import AlertHistory, AlertRule, User
from backend.database.repositories import (
    AlertHistoryRepository,
    AlertRuleRepository,
    UserRepository,
)


class AlertServiceError(Exception):
    """Raised for validation / business-rule violations (safe to show users)."""


@dataclass(slots=True)
class StatusSummary:
    active_rules: int
    total_alerts: int
    last_alert_at: datetime | None


class AlertService:
    """Create/list/remove rules and read history -- shared by bot and API."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.rules = AlertRuleRepository(session)
        self.history = AlertHistoryRepository(session)

    # ------------------------------------------------------------------ #
    # Rules                                                               #
    # ------------------------------------------------------------------ #
    async def create_rule(
        self,
        user: User,
        token: str,
        threshold_usd: float | int | str,
        event_type: EventType = EventType.ANY,
        raw_request: str | None = None,
    ) -> AlertRule:
        """Validate inputs and create (or update) an alert rule for ``user``."""
        symbol = validate_token_symbol(token)
        threshold = validate_threshold(threshold_usd)

        # Enforce the per-user ceiling (only counts brand-new rules).
        existing = await self.rules.find_active(user.id, symbol, event_type)
        if existing is None:
            count = await self.rules.count_active_for_user(user.id)
            if count >= settings.MAX_ALERTS_PER_USER:
                raise AlertServiceError(
                    f"You've reached the maximum of {settings.MAX_ALERTS_PER_USER} "
                    "active alerts. Remove one with /untrack first."
                )

        meta = resolve_token(symbol)
        token_address = str(meta["address"]) if meta else None

        return await self.rules.create(
            user_id=user.id,
            token_symbol=symbol,
            threshold_usd=threshold,
            event_type=event_type,
            token_address=token_address,
            raw_request=raw_request,
        )

    async def list_rules(self, user: User) -> list[AlertRule]:
        return await self.rules.list_for_user(user.id, active_only=True)

    async def remove_token(self, user: User, token: str) -> int:
        """Deactivate all of a user's rules for a token. Returns count removed."""
        symbol = validate_token_symbol(token)
        return await self.rules.deactivate_by_token(user.id, symbol)

    async def delete_rule(self, user: User, rule_id: int) -> bool:
        rule = await self.rules.get_by_id(rule_id)
        if rule is None or rule.user_id != user.id:
            return False
        await self.rules.deactivate(rule)
        return True

    # ------------------------------------------------------------------ #
    # History & status                                                    #
    # ------------------------------------------------------------------ #
    async def recent_history(
        self, user: User, limit: int = 20, today_only: bool = False
    ) -> list[AlertHistory]:
        if today_only:
            return await self.history.todays_for_user(user.id, limit=limit)
        return await self.history.list_for_user(user.id, limit=limit)

    async def status(self, user: User) -> StatusSummary:
        active = await self.rules.count_active_for_user(user.id)
        total = await self.history.count_for_user(user.id)
        last = await self.history.last_for_user(user.id)
        return StatusSummary(
            active_rules=active,
            total_alerts=total,
            last_alert_at=last.created_at if last else None,
        )

    async def set_notifications(self, user: User, enabled: bool) -> None:
        await self.users.set_notifications(user, enabled)

    # ------------------------------------------------------------------ #
    # Intent application (natural-language entry point)                   #
    # ------------------------------------------------------------------ #
    async def apply_create_intent(self, user: User, intent: ExtractedIntent) -> AlertRule:
        """Create a rule from a validated CREATE/MODIFY intent."""
        if intent.token is None or intent.threshold_usd is None:
            raise AlertServiceError("I need both a token and a USD threshold.")
        if intent.intent not in (IntentType.CREATE_ALERT, IntentType.MODIFY_ALERT):
            raise AlertServiceError("That isn't a tracking request.")
        return await self.create_rule(
            user=user,
            token=intent.token,
            threshold_usd=intent.threshold_usd,
            event_type=intent.event_type,
            raw_request=intent.raw_text,
        )
