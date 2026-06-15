"""
Rule-matching predicates.

Pure functions deciding whether a :class:`WhaleTransaction` satisfies an
:class:`AlertRule`. Kept dependency-free and side-effect-free so they are
trivially unit-testable.
"""

from __future__ import annotations

from backend.core.domain import WhaleTransaction
from backend.core.types import EventType, TransactionDirection, normalize_symbol
from backend.database.models import AlertRule


def event_type_matches(rule_event: EventType, whale: WhaleTransaction) -> bool:
    """Does the whale's event/direction satisfy the rule's event_type filter?"""
    if rule_event == EventType.ANY:
        return True
    direction = whale.event.direction
    if rule_event == EventType.BUY:
        return direction == TransactionDirection.BUY
    if rule_event == EventType.SELL:
        return direction == TransactionDirection.SELL
    if rule_event == EventType.SWAP:
        return whale.event.event_type == EventType.SWAP
    if rule_event == EventType.TRANSFER:
        return whale.event.event_type == EventType.TRANSFER
    return False


def rule_matches(rule: AlertRule, whale: WhaleTransaction) -> bool:
    """True if the whale transaction should trigger this rule."""
    if not rule.is_active:
        return False
    if normalize_symbol(rule.token_symbol) != normalize_symbol(whale.event.token_symbol):
        return False
    if whale.value_usd < rule.threshold_usd:
        return False
    return event_type_matches(rule.event_type, whale)
