"""
Alert engine: turns whale transactions into delivered, de-duplicated alerts.

Flow for each :class:`WhaleTransaction`:
  1. Find active rules whose token/event/threshold match.
  2. For each matching rule (per user), enforce idempotency via (rule_id,
     dedup_key) so the same on-chain action never alerts twice.
  3. Generate an AI insight (with 24h-average context).
  4. Persist an :class:`AlertHistory` row.
  5. Deliver the Telegram message via the injected notifier.
  6. Optionally write an on-chain fingerprint.

The engine receives a ``notifier`` callable -- ``async (chat_id, html) -> bool``
-- so it has no hard dependency on python-telegram-bot and stays unit-testable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from backend.ai.insights import InsightGenerator, get_insight_generator
from backend.alerts.matching import rule_matches
from backend.alerts.onchain_logger import OnChainLogger, get_onchain_logger
from backend.bot.formatters import format_whale_alert
from backend.core.domain import WhaleTransaction
from backend.core.logging import get_logger
from backend.core.types import AlertStatus
from backend.database.models import AlertHistory
from backend.database.repositories import (
    AlertHistoryRepository,
    AlertRuleRepository,
    UserRepository,
)
from backend.database.session import session_scope

logger = get_logger(__name__)

Notifier = Callable[[int, str], Awaitable[bool]]


class AlertEngine:
    """Matches whales to rules and dispatches Telegram alerts."""

    def __init__(
        self,
        notifier: Notifier | None = None,
        insight_generator: InsightGenerator | None = None,
        onchain_logger: OnChainLogger | None = None,
    ) -> None:
        self._notifier = notifier
        self._insights = insight_generator or get_insight_generator()
        self._onchain = onchain_logger or get_onchain_logger()

    def set_notifier(self, notifier: Notifier) -> None:
        """Attach the delivery callback after construction (bot wires this in)."""
        self._notifier = notifier

    async def handle_whale(self, whale: WhaleTransaction) -> int:
        """Process one whale transaction. Returns number of alerts delivered."""
        delivered = 0
        async with session_scope() as session:
            rule_repo = AlertRuleRepository(session)
            user_repo = UserRepository(session)
            history_repo = AlertHistoryRepository(session)

            active_rules = await rule_repo.list_all_active()
            matches = [r for r in active_rules if rule_matches(r, whale)]
            if not matches:
                return 0

            avg_value = await self._avg_value_24h(session, whale.event.token_symbol)
            insight = await self._insights.generate(whale, avg_value)

            for rule in matches:
                # Idempotency guard.
                if await history_repo.exists(rule.id, whale.dedup_key):
                    continue

                user = await user_repo.get_by_id(rule.user_id)
                if user is None or not user.is_active:
                    continue

                alert = AlertHistory(
                    user_id=user.id,
                    rule_id=rule.id,
                    token_symbol=whale.event.token_symbol,
                    event_type=whale.event.event_type,
                    direction=whale.event.direction.value,
                    tx_hash=whale.event.tx_hash,
                    log_index=whale.event.log_index,
                    block_number=whale.event.block_number,
                    from_address=whale.event.from_address,
                    to_address=whale.event.to_address,
                    token_amount=whale.event.amount,
                    token_price_usd=whale.token_price_usd,
                    value_usd=whale.value_usd,
                    insight=insight,
                    dedup_key=whale.dedup_key,
                    status=AlertStatus.PENDING,
                )
                await history_repo.create(alert)

                # Deliver (respecting per-user notification preference).
                if user.notifications_enabled:
                    ok = await self._deliver(user.chat_id, whale, insight)
                    alert.status = AlertStatus.SENT if ok else AlertStatus.FAILED
                    if ok:
                        delivered += 1
                else:
                    alert.status = AlertStatus.SUPPRESSED

                # Best-effort on-chain fingerprint (only once per action is enough,
                # but logging per alert keeps the contract's per-user audit trail).
                onchain_tx = await self._onchain.log_alert(whale)
                if onchain_tx:
                    alert.onchain_log_tx = onchain_tx

        return delivered

    async def _deliver(self, chat_id: int, whale: WhaleTransaction, insight: str) -> bool:
        if self._notifier is None:
            logger.warning("alert.no_notifier", chat_id=chat_id)
            return False
        try:
            message = format_whale_alert(whale, insight)
            return await self._notifier(chat_id, message)
        except Exception as exc:
            logger.error("alert.delivery_failed", chat_id=chat_id, error=str(exc))
            return False

    async def _avg_value_24h(self, session, token_symbol: str) -> float | None:
        """Average alert USD value for a token over the last 24h (insight context)."""
        since = datetime.now(UTC) - timedelta(hours=24)
        result = await session.execute(
            select(func.avg(AlertHistory.value_usd)).where(
                AlertHistory.token_symbol == token_symbol,
                AlertHistory.created_at >= since,
            )
        )
        avg = result.scalar_one_or_none()
        return float(avg) if avg else None


_singleton: AlertEngine | None = None


def get_alert_engine() -> AlertEngine:
    """Return a process-wide :class:`AlertEngine` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = AlertEngine()
    return _singleton
