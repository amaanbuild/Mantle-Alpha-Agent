"""Initial schema: users, alert_rules, tracked_tokens, alert_history, system_logs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("language_code", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.create_table(
        "tracked_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("address", sa.String(42), nullable=False),
        sa.Column("decimals", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("coingecko_id", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", name="uq_tracked_tokens_symbol"),
    )
    op.create_index("ix_tracked_tokens_symbol", "tracked_tokens", ["symbol"])
    op.create_index("ix_tracked_tokens_address", "tracked_tokens", ["address"])

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_symbol", sa.String(32), nullable=False),
        sa.Column("token_address", sa.String(42), nullable=True),
        sa.Column("event_type", sa.String(16), nullable=False, server_default="any"),
        sa.Column("threshold_usd", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("raw_request", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "token_symbol", "event_type", name="uq_user_token_event"
        ),
    )
    op.create_index("ix_alert_rules_user_id", "alert_rules", ["user_id"])
    op.create_index("ix_alert_rules_token_symbol", "alert_rules", ["token_symbol"])
    op.create_index(
        "ix_alert_rules_active_token", "alert_rules", ["is_active", "token_symbol"]
    )

    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("token_symbol", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(16), nullable=True),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("log_index", sa.Integer(), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("from_address", sa.String(42), nullable=True),
        sa.Column("to_address", sa.String(42), nullable=True),
        sa.Column("token_amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("token_price_usd", sa.Float(), nullable=True),
        sa.Column("value_usd", sa.Float(), nullable=False),
        sa.Column("insight", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("dedup_key", sa.String(80), nullable=False),
        sa.Column("onchain_log_tx", sa.String(66), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("rule_id", "dedup_key", name="uq_rule_dedup"),
    )
    op.create_index("ix_alert_history_user_id", "alert_history", ["user_id"])
    op.create_index("ix_alert_history_rule_id", "alert_history", ["rule_id"])
    op.create_index("ix_alert_history_dedup_key", "alert_history", ["dedup_key"])
    op.create_index("ix_alert_history_tx", "alert_history", ["tx_hash"])
    op.create_index(
        "ix_alert_history_user_created", "alert_history", ["user_id", "created_at"]
    )

    op.create_table(
        "system_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="INFO"),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
    )
    op.create_index("ix_system_logs_created_at", "system_logs", ["created_at"])
    op.create_index(
        "ix_system_logs_level_created", "system_logs", ["level", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("system_logs")
    op.drop_table("alert_history")
    op.drop_table("alert_rules")
    op.drop_table("tracked_tokens")
    op.drop_table("users")
