"""
Plain domain objects passed between subsystems.

These are framework-agnostic dataclasses (not ORM rows, not Pydantic request
models). They are the lingua franca between the blockchain monitor, the whale
detector, the pricing service, the insight generator, and the alert engine.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from backend.core.types import EventType, IntentType, TransactionDirection


@dataclass(slots=True)
class ExtractedIntent:
    """Structured result of parsing a natural-language user message."""

    intent: IntentType
    token: str | None = None
    event_type: EventType = EventType.ANY
    threshold_usd: float | None = None
    # The original text, retained for auditing / storage on the rule.
    raw_text: str = ""
    # 0..1 model confidence; rule-based fallback sets a conservative value.
    confidence: float = 1.0
    # Human-readable note when intent == UNKNOWN (used in clarification replies).
    note: str | None = None

    def is_actionable(self) -> bool:
        return self.intent != IntentType.UNKNOWN


@dataclass(slots=True)
class ChainEvent:
    """A normalized on-chain event (ERC-20 Transfer or DEX Swap)."""

    event_type: EventType
    token_symbol: str
    token_address: str
    token_decimals: int
    # Raw integer amount (token base units) and human-decimal amount.
    raw_amount: int
    amount: Decimal
    from_address: str
    to_address: str
    tx_hash: str
    log_index: int
    block_number: int
    direction: TransactionDirection = TransactionDirection.TRANSFER
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class WhaleTransaction:
    """A :class:`ChainEvent` that has been priced and judged whale-sized."""

    event: ChainEvent
    token_price_usd: float
    value_usd: float

    @property
    def dedup_key(self) -> str:
        """
        Stable identifier for this on-chain action.

        Combines tx hash + log index + token, so the same transfer never alerts
        twice even across restarts. Per-rule uniqueness is enforced at the DB
        layer using (rule_id, dedup_key).
        """
        seed = f"{self.event.tx_hash}:{self.event.log_index}:{self.event.token_address}"
        return hashlib.sha256(seed.encode()).hexdigest()[:64]

    @property
    def short_from(self) -> str:
        return _shorten(self.event.from_address)

    @property
    def short_to(self) -> str:
        return _shorten(self.event.to_address)


def _shorten(address: str | None) -> str:
    """Render 0x1234...abcd style short addresses for display."""
    if not address or len(address) < 12:
        return address or "?"
    return f"{address[:6]}...{address[-4:]}"
