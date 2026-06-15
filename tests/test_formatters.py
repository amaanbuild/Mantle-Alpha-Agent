"""Tests for Telegram message formatting and event decoding helpers."""

from __future__ import annotations

from decimal import Decimal

from backend.bot import formatters
from backend.core.domain import ChainEvent, WhaleTransaction
from backend.core.types import EventType, TransactionDirection
from backend.database.models import AlertRule


def _whale() -> WhaleTransaction:
    event = ChainEvent(
        event_type=EventType.TRANSFER,
        token_symbol="mETH",
        token_address="0xcDA86A272531e8640cD7F1a92c01839911B90bb0",
        token_decimals=18,
        raw_amount=int(Decimal("37.6") * (10**18)),
        amount=Decimal("37.6"),
        from_address="0x1234567890abcdef1234567890abcdef12345678",
        to_address="0xabcdef1234567890abcdef1234567890abcdef12",
        tx_hash="0x" + "a" * 64,
        log_index=3,
        block_number=200,
        direction=TransactionDirection.BUY,
    )
    return WhaleTransaction(event=event, token_price_usd=3200.0, value_usd=120_320.0)


def test_format_whale_alert_contains_key_fields():
    msg = formatters.format_whale_alert(_whale(), "Large accumulation detected.")
    assert "Whale Alert" in msg
    assert "mETH" in msg
    assert "$120,320" in msg
    assert "0x1234...5678" in msg
    assert "AI Insight" in msg
    assert "explorer.mantle.xyz/tx/" in msg


def test_format_rule_created():
    rule = AlertRule(user_id=1, token_symbol="METH", threshold_usd=10_000, event_type=EventType.ANY)
    msg = formatters.format_rule_created(rule)
    assert "METH" in msg
    assert "$10,000" in msg


def test_format_my_alerts_empty():
    assert "no active alerts" in formatters.format_my_alerts([]).lower()


def test_format_my_alerts_lists_rules():
    rules = [
        AlertRule(user_id=1, token_symbol="METH", threshold_usd=10_000, event_type=EventType.ANY),
        AlertRule(user_id=1, token_symbol="MNT", threshold_usd=50_000, event_type=EventType.BUY),
    ]
    msg = formatters.format_my_alerts(rules)
    assert "METH" in msg and "MNT" in msg
    assert "(buy)" in msg


def test_format_status():
    msg = formatters.format_status(active_rules=3, total_alerts=12, last_alert=None, rpc_ok=True)
    assert "3" in msg and "12" in msg
    assert "Operational" in msg


def test_html_escaping_prevents_injection():
    # A malicious insight should be escaped, not break the markup.
    msg = formatters.format_whale_alert(_whale(), "<script>alert(1)</script>")
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg
