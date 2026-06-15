"""
SQLAlchemy ORM models (declarative, 2.0 typed style).

Tables
------
- users            : Telegram users known to the bot.
- alert_rules      : Per-user monitoring rules ("track mETH > $10k").
- alert_history    : Concrete alerts that fired for a rule / transaction.
- tracked_tokens   : Token registry (symbol -> address / decimals / price id).
- system_logs      : Structured audit / health events for observability.

All timestamps are stored in UTC. Monetary/amount values that must keep
precision use ``Numeric``; convenience denormalized USD values use ``Float``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.core.types import AlertStatus, EventType


def _utcnow() -> datetime:
    """Timezone-aware UTC now (used as a column default)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    """Adds created_at / updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class User(Base, TimestampMixin):
    """A Telegram user interacting with the bot."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Telegram numeric user id (unique, stable per user).
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    # Telegram chat id to deliver alerts to (usually == telegram_id for DMs).
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # JSON-ish notification preferences stored as text (kept simple/portable).
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)

    rules: Mapped[list[AlertRule]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    alerts: Mapped[list[AlertHistory]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AlertRule(Base, TimestampMixin):
    """A monitoring rule: alert when <token> has <event_type> >= <threshold_usd>."""

    __tablename__ = "alert_rules"
    __table_args__ = (
        # A user should not have two identical active rules.
        UniqueConstraint("user_id", "token_symbol", "event_type", name="uq_user_token_event"),
        Index("ix_alert_rules_active_token", "is_active", "token_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    token_symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Optional explicit token contract address (else resolved from registry).
    token_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    event_type: Mapped[EventType] = mapped_column(String(16), default=EventType.ANY, nullable=False)
    threshold_usd: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Free-text the user originally typed (for audit / re-parsing).
    raw_request: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="rules")
    alerts: Mapped[list[AlertHistory]] = relationship(back_populates="rule")


class TrackedToken(Base, TimestampMixin):
    """Registry of tokens the system understands (symbol/address/decimals/price id)."""

    __tablename__ = "tracked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address: Mapped[str] = mapped_column(String(42), index=True, nullable=False)
    decimals: Mapped[int] = mapped_column(default=18, nullable=False)
    coingecko_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AlertHistory(Base, TimestampMixin):
    """A concrete alert that fired (one per matched whale transaction per rule)."""

    __tablename__ = "alert_history"
    __table_args__ = (
        # Idempotency: never fire the same rule for the same tx + log twice.
        UniqueConstraint("rule_id", "dedup_key", name="uq_rule_dedup"),
        Index("ix_alert_history_user_created", "user_id", "created_at"),
        Index("ix_alert_history_tx", "tx_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="SET NULL"), index=True, nullable=True
    )

    token_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[EventType] = mapped_column(String(16), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # On-chain facts.
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    log_index: Mapped[int | None] = mapped_column(nullable=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    to_address: Mapped[str | None] = mapped_column(String(42), nullable=True)

    # Valuation.
    token_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    token_price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # AI-generated insight text shown to the user.
    insight: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[AlertStatus] = mapped_column(
        String(16), default=AlertStatus.PENDING, nullable=False
    )
    # Stable hash used both for in-DB dedup and on-chain logging.
    dedup_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # On-chain logger receipt hash (if ENABLE_ONCHAIN_LOGGING).
    onchain_log_tx: Mapped[str | None] = mapped_column(String(66), nullable=True)

    user: Mapped[User] = relationship(back_populates="alerts")
    rule: Mapped[AlertRule | None] = relationship(back_populates="alerts")


class SystemLog(Base):
    """Structured audit / health events for observability and debugging."""

    __tablename__ = "system_logs"
    __table_args__ = (Index("ix_system_logs_level_created", "level", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional JSON-encoded context payload.
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
