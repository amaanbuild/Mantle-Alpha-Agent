"""End-to-end tests for the alert engine (whale -> matched rule -> delivery)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from backend.alerts.engine import AlertEngine
from backend.alerts.service import AlertService
from backend.core.domain import ChainEvent, WhaleTransaction
from backend.core.types import AlertStatus, EventType, TransactionDirection
from backend.database.repositories import AlertHistoryRepository
from backend.database.session import session_scope


def _whale(symbol="METH", value=15_000.0, tx="0xdeadbeef") -> WhaleTransaction:
    event = ChainEvent(
        event_type=EventType.TRANSFER,
        token_symbol=symbol,
        token_address="0xcDA86A272531e8640cD7F1a92c01839911B90bb0",
        token_decimals=18,
        raw_amount=int(Decimal("5") * (10**18)),
        amount=Decimal("5"),
        from_address="0x1111111111111111111111111111111111111111",
        to_address="0x2222222222222222222222222222222222222222",
        tx_hash=tx,
        log_index=0,
        block_number=100,
        direction=TransactionDirection.BUY,
    )
    return WhaleTransaction(event=event, token_price_usd=3000.0, value_usd=value)


class _Notifier:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    async def send(self, chat_id: int, html: str) -> bool:
        self.calls.append((chat_id, html))
        return True


@pytest.fixture
async def user_with_rule(session):
    service = AlertService(session)
    user = await service.users.get_or_create(telegram_id=555, chat_id=555, username="whale-watcher")
    await service.create_rule(user, "METH", 10_000, EventType.ANY)
    await session.commit()
    return user


async def test_whale_triggers_delivery(db_engine, user_with_rule):
    notifier = _Notifier()
    engine = AlertEngine(notifier=notifier.send)

    delivered = await engine.handle_whale(_whale())
    assert delivered == 1
    assert len(notifier.calls) == 1
    chat_id, html = notifier.calls[0]
    assert chat_id == 555
    assert "Whale Alert" in html
    assert "mETH" in html or "METH" in html


async def test_alert_persisted_with_insight(db_engine, user_with_rule):
    notifier = _Notifier()
    engine = AlertEngine(notifier=notifier.send)
    await engine.handle_whale(_whale())

    async with session_scope() as s:
        alerts = await AlertHistoryRepository(s).list_for_user(user_with_rule.id, limit=10)
    assert len(alerts) == 1
    assert alerts[0].status == AlertStatus.SENT
    assert alerts[0].insight  # template insight present
    assert alerts[0].value_usd == pytest.approx(15_000)


async def test_dedup_prevents_double_alert(db_engine, user_with_rule):
    notifier = _Notifier()
    engine = AlertEngine(notifier=notifier.send)
    await engine.handle_whale(_whale(tx="0xsame"))
    delivered_again = await engine.handle_whale(_whale(tx="0xsame"))
    assert delivered_again == 0
    assert len(notifier.calls) == 1


async def test_below_threshold_no_match(db_engine, user_with_rule):
    notifier = _Notifier()
    engine = AlertEngine(notifier=notifier.send)
    delivered = await engine.handle_whale(_whale(value=500.0))
    assert delivered == 0
    assert notifier.calls == []


async def test_notifications_disabled_suppresses(db_engine, session):
    service = AlertService(session)
    user = await service.users.get_or_create(telegram_id=777, chat_id=777)
    await service.create_rule(user, "METH", 10_000)
    await service.set_notifications(user, False)
    await session.commit()

    notifier = _Notifier()
    engine = AlertEngine(notifier=notifier.send)
    delivered = await engine.handle_whale(_whale())
    assert delivered == 0
    assert notifier.calls == []

    async with session_scope() as s:
        alerts = await AlertHistoryRepository(s).list_for_user(user.id, limit=10)
    assert alerts[0].status == AlertStatus.SUPPRESSED
