"""Tests for whale detection and rule matching."""

from __future__ import annotations

from decimal import Decimal

import pytest
from backend.alerts.matching import event_type_matches, rule_matches
from backend.blockchain.whale import WhaleDetector
from backend.core.domain import ChainEvent, WhaleTransaction
from backend.core.types import EventType, TransactionDirection
from backend.database.models import AlertRule


class _StubPrices:
    def __init__(self, price: float | None) -> None:
        self._price = price

    async def get_price(self, symbol: str):  # noqa: ARG002
        return self._price


def _event(symbol="METH", amount="2", direction=TransactionDirection.BUY) -> ChainEvent:
    return ChainEvent(
        event_type=EventType.TRANSFER,
        token_symbol=symbol,
        token_address="0xcDA86A272531e8640cD7F1a92c01839911B90bb0",
        token_decimals=18,
        raw_amount=int(Decimal(amount) * (10**18)),
        amount=Decimal(amount),
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x2222222222222222222222222222222222222222",
        tx_hash="0xabc",
        log_index=0,
        block_number=100,
        direction=direction,
    )


async def test_whale_detected_above_threshold():
    detector = WhaleDetector(price_service=_StubPrices(3000.0))
    whale = await detector.evaluate(_event(amount="5"), min_threshold_usd=10_000)
    assert whale is not None
    assert whale.value_usd == pytest.approx(15_000)


async def test_below_threshold_returns_none():
    detector = WhaleDetector(price_service=_StubPrices(3000.0))
    whale = await detector.evaluate(_event(amount="1"), min_threshold_usd=10_000)
    assert whale is None


async def test_no_price_returns_none():
    detector = WhaleDetector(price_service=_StubPrices(None))
    assert await detector.evaluate(_event(), min_threshold_usd=100) is None


def test_dedup_key_is_stable():
    w1 = WhaleTransaction(event=_event(), token_price_usd=3000, value_usd=6000)
    w2 = WhaleTransaction(event=_event(), token_price_usd=3000, value_usd=6000)
    assert w1.dedup_key == w2.dedup_key


def _rule(symbol="METH", threshold=10_000, event_type=EventType.ANY) -> AlertRule:
    return AlertRule(
        user_id=1,
        token_symbol=symbol,
        threshold_usd=threshold,
        event_type=event_type,
        is_active=True,
    )


def test_rule_matches_token_and_threshold():
    whale = WhaleTransaction(event=_event(amount="5"), token_price_usd=3000, value_usd=15_000)
    assert rule_matches(_rule(), whale)


def test_rule_does_not_match_other_token():
    whale = WhaleTransaction(event=_event(amount="5"), token_price_usd=3000, value_usd=15_000)
    assert not rule_matches(_rule(symbol="MNT"), whale)


def test_rule_below_threshold_no_match():
    whale = WhaleTransaction(event=_event(amount="1"), token_price_usd=3000, value_usd=3000)
    assert not rule_matches(_rule(threshold=10_000), whale)


def test_event_type_filter():
    buy_whale = WhaleTransaction(
        event=_event(direction=TransactionDirection.BUY), token_price_usd=1, value_usd=99999
    )
    assert event_type_matches(EventType.BUY, buy_whale)
    assert not event_type_matches(EventType.SELL, buy_whale)
    assert event_type_matches(EventType.ANY, buy_whale)
