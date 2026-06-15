"""Tests for the repository / service data-access layer."""

from __future__ import annotations

import pytest
from backend.alerts.service import AlertService, AlertServiceError
from backend.core.types import EventType
from backend.database.repositories import (
    AlertRuleRepository,
    UserRepository,
)


async def test_user_get_or_create_idempotent(session):
    repo = UserRepository(session)
    u1 = await repo.get_or_create(telegram_id=999, chat_id=999, username="a")
    await session.commit()
    u2 = await repo.get_or_create(telegram_id=999, chat_id=999, username="a2")
    await session.commit()
    assert u1.id == u2.id
    assert u2.username == "a2"  # profile refreshed


async def test_create_rule_and_list(session, user):
    service = AlertService(session)
    rule = await service.create_rule(user, "mETH", 10_000, EventType.ANY)
    await session.commit()
    assert rule.token_symbol == "METH"
    assert rule.threshold_usd == 10_000

    rules = await service.list_rules(user)
    assert len(rules) == 1


async def test_create_rule_upsert_updates_threshold(session, user):
    service = AlertService(session)
    await service.create_rule(user, "MNT", 10_000)
    await session.commit()
    await service.create_rule(user, "MNT", 50_000)
    await session.commit()
    rules = await service.list_rules(user)
    assert len(rules) == 1
    assert rules[0].threshold_usd == 50_000


async def test_remove_token(session, user):
    service = AlertService(session)
    await service.create_rule(user, "MNT", 10_000)
    await session.commit()
    removed = await service.remove_token(user, "MNT")
    await session.commit()
    assert removed == 1
    assert await service.list_rules(user) == []


async def test_create_rule_rejects_low_threshold(session, user):
    service = AlertService(session)
    with pytest.raises(ValueError):
        await service.create_rule(user, "MNT", 1)


async def test_max_alerts_enforced(session, user, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "MAX_ALERTS_PER_USER", 2)
    service = AlertService(session)
    await service.create_rule(user, "MNT", 10_000)
    await service.create_rule(user, "METH", 10_000)
    await session.commit()
    with pytest.raises(AlertServiceError):
        await service.create_rule(user, "USDC", 10_000)


async def test_status_summary(session, user):
    service = AlertService(session)
    await service.create_rule(user, "MNT", 10_000)
    await session.commit()
    summary = await service.status(user)
    assert summary.active_rules == 1
    assert summary.total_alerts == 0
    assert summary.last_alert_at is None


async def test_count_active_for_user(session, user):
    repo = AlertRuleRepository(session)
    await repo.create(user.id, "MNT", 10_000)
    await repo.create(user.id, "METH", 20_000)
    await session.commit()
    assert await repo.count_active_for_user(user.id) == 2
