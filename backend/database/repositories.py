"""
Repository layer (data-access objects).

Encapsulates all CRUD so business logic never writes raw queries. Repositories
take an :class:`AsyncSession` and do **not** commit -- the caller controls the
transaction boundary (via ``session_scope`` or the FastAPI dependency). This
keeps transactions atomic across multiple repository calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.core.types import AlertStatus, EventType, normalize_symbol
from backend.database.models import (
    AlertHistory,
    AlertRule,
    SystemLog,
    TrackedToken,
    User,
)


class UserRepository:
    """CRUD for :class:`User`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_or_create(
        self,
        telegram_id: int,
        chat_id: int,
        username: str | None = None,
        first_name: str | None = None,
        language_code: str | None = None,
    ) -> User:
        """Fetch an existing user or create one (upserting volatile profile fields)."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(
                telegram_id=telegram_id,
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                language_code=language_code,
            )
            self.session.add(user)
            await self.session.flush()
            return user

        # Keep mutable profile fields fresh.
        user.chat_id = chat_id
        if username is not None:
            user.username = username
        if first_name is not None:
            user.first_name = first_name
        return user

    async def set_notifications(self, user: User, enabled: bool) -> None:
        user.notifications_enabled = enabled

    async def list_active(self) -> list[User]:
        result = await self.session.execute(select(User).where(User.is_active.is_(True)))
        return list(result.scalars().all())


class AlertRuleRepository:
    """CRUD for :class:`AlertRule`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, rule_id: int) -> AlertRule | None:
        return await self.session.get(AlertRule, rule_id)

    async def list_for_user(self, user_id: int, active_only: bool = True) -> list[AlertRule]:
        stmt = select(AlertRule).where(AlertRule.user_id == user_id)
        if active_only:
            stmt = stmt.where(AlertRule.is_active.is_(True))
        stmt = stmt.order_by(AlertRule.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_active(self) -> list[AlertRule]:
        """All active rules across all users (consumed by the alert engine)."""
        result = await self.session.execute(select(AlertRule).where(AlertRule.is_active.is_(True)))
        return list(result.scalars().all())

    async def count_active_for_user(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(AlertRule)
            .where(AlertRule.user_id == user_id, AlertRule.is_active.is_(True))
        )
        return int(result.scalar_one())

    async def find_active(
        self, user_id: int, token_symbol: str, event_type: EventType
    ) -> AlertRule | None:
        result = await self.session.execute(
            select(AlertRule).where(
                AlertRule.user_id == user_id,
                AlertRule.token_symbol == normalize_symbol(token_symbol),
                AlertRule.event_type == event_type,
                AlertRule.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: int,
        token_symbol: str,
        threshold_usd: float,
        event_type: EventType = EventType.ANY,
        token_address: str | None = None,
        raw_request: str | None = None,
    ) -> AlertRule:
        """
        Create or revive a rule (idempotent on user+token+event).

        If an identical rule exists (active or not) its threshold is updated and
        it is reactivated, mirroring "track again with a new amount".
        """
        symbol = normalize_symbol(token_symbol)
        existing = await self.session.execute(
            select(AlertRule).where(
                AlertRule.user_id == user_id,
                AlertRule.token_symbol == symbol,
                AlertRule.event_type == event_type,
            )
        )
        rule = existing.scalar_one_or_none()
        if rule is not None:
            rule.threshold_usd = threshold_usd
            rule.is_active = True
            if token_address:
                rule.token_address = token_address
            if raw_request:
                rule.raw_request = raw_request
            return rule

        rule = AlertRule(
            user_id=user_id,
            token_symbol=symbol,
            token_address=token_address,
            event_type=event_type,
            threshold_usd=threshold_usd,
            raw_request=raw_request,
        )
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def update_threshold(self, rule: AlertRule, threshold_usd: float) -> None:
        rule.threshold_usd = threshold_usd

    async def deactivate(self, rule: AlertRule) -> None:
        rule.is_active = False

    async def deactivate_by_token(self, user_id: int, token_symbol: str) -> int:
        """Deactivate all of a user's rules for a token. Returns count affected."""
        symbol = normalize_symbol(token_symbol)
        result = await self.session.execute(
            update(AlertRule)
            .where(
                AlertRule.user_id == user_id,
                AlertRule.token_symbol == symbol,
                AlertRule.is_active.is_(True),
            )
            .values(is_active=False)
        )
        return result.rowcount or 0

    async def delete(self, rule: AlertRule) -> None:
        await self.session.delete(rule)


class AlertHistoryRepository:
    """CRUD for :class:`AlertHistory`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, rule_id: int, dedup_key: str) -> bool:
        result = await self.session.execute(
            select(func.count())
            .select_from(AlertHistory)
            .where(AlertHistory.rule_id == rule_id, AlertHistory.dedup_key == dedup_key)
        )
        return int(result.scalar_one()) > 0

    async def create(self, alert: AlertHistory) -> AlertHistory:
        self.session.add(alert)
        await self.session.flush()
        return alert

    async def get_by_id(self, alert_id: int) -> AlertHistory | None:
        return await self.session.get(AlertHistory, alert_id)

    async def list_for_user(
        self, user_id: int, limit: int = 20, since: datetime | None = None
    ) -> list[AlertHistory]:
        stmt = select(AlertHistory).where(AlertHistory.user_id == user_id)
        if since is not None:
            stmt = stmt.where(AlertHistory.created_at >= since)
        stmt = stmt.order_by(AlertHistory.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 50) -> list[AlertHistory]:
        result = await self.session.execute(
            select(AlertHistory).order_by(AlertHistory.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def count_for_user(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(AlertHistory).where(AlertHistory.user_id == user_id)
        )
        return int(result.scalar_one())

    async def last_for_user(self, user_id: int) -> AlertHistory | None:
        result = await self.session.execute(
            select(AlertHistory)
            .where(AlertHistory.user_id == user_id)
            .order_by(AlertHistory.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def todays_for_user(self, user_id: int, limit: int = 50) -> list[AlertHistory]:
        midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.list_for_user(user_id, limit=limit, since=midnight)

    async def mark_status(self, alert: AlertHistory, status: AlertStatus) -> None:
        alert.status = status


class TrackedTokenRepository:
    """CRUD for :class:`TrackedToken`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_symbol(self, symbol: str) -> TrackedToken | None:
        result = await self.session.execute(
            select(TrackedToken).where(TrackedToken.symbol == normalize_symbol(symbol))
        )
        return result.scalar_one_or_none()

    async def get_by_address(self, address: str) -> TrackedToken | None:
        result = await self.session.execute(
            select(TrackedToken).where(func.lower(TrackedToken.address) == address.lower())
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[TrackedToken]:
        result = await self.session.execute(
            select(TrackedToken).where(TrackedToken.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        symbol: str,
        address: str,
        decimals: int = 18,
        name: str | None = None,
        coingecko_id: str | None = None,
    ) -> TrackedToken:
        token = await self.get_by_symbol(symbol)
        if token is None:
            token = TrackedToken(
                symbol=normalize_symbol(symbol),
                address=address,
                decimals=decimals,
                name=name,
                coingecko_id=coingecko_id,
            )
            self.session.add(token)
            await self.session.flush()
            return token
        token.address = address
        token.decimals = decimals
        if name:
            token.name = name
        if coingecko_id:
            token.coingecko_id = coingecko_id
        return token


class SystemLogRepository:
    """Append-only writer for :class:`SystemLog`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self, component: str, message: str, level: str = "INFO", context: str | None = None
    ) -> None:
        self.session.add(
            SystemLog(component=component, message=message, level=level, context=context)
        )

    async def purge_older_than(self, days: int = 30) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self.session.execute(delete(SystemLog).where(SystemLog.created_at < cutoff))
        return result.rowcount or 0


def max_alerts_per_user() -> int:
    """Configured ceiling on active rules per user (used by services)."""
    return settings.MAX_ALERTS_PER_USER
