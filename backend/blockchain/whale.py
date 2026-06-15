"""
Whale detection engine.

Prices each :class:`ChainEvent` via the :class:`PriceService` and decides whether
it clears a USD threshold to become a :class:`WhaleTransaction`. The minimum
gate is the smallest *active rule* threshold (so we never price/forward events
no one cares about), defaulting to ``MIN_WHALE_THRESHOLD_USD``.
"""

from __future__ import annotations

from backend.config import settings
from backend.core.domain import ChainEvent, WhaleTransaction
from backend.core.logging import get_logger
from backend.pricing.service import PriceService, get_price_service

logger = get_logger(__name__)


class WhaleDetector:
    """Values events in USD and flags whale-sized transactions."""

    def __init__(self, price_service: PriceService | None = None) -> None:
        self.prices = price_service or get_price_service()

    async def evaluate(
        self, event: ChainEvent, min_threshold_usd: float | None = None
    ) -> WhaleTransaction | None:
        """
        Price ``event`` and return a :class:`WhaleTransaction` if it clears the
        minimum threshold, else ``None``.
        """
        gate = (
            min_threshold_usd if min_threshold_usd is not None else settings.MIN_WHALE_THRESHOLD_USD
        )

        price = await self.prices.get_price(event.token_symbol)
        if price is None:
            # No price -> cannot value -> cannot whale-judge. Skip quietly.
            logger.debug("whale.no_price", symbol=event.token_symbol, tx=event.tx_hash)
            return None

        value_usd = float(price) * float(event.amount)
        if value_usd < gate:
            return None

        whale = WhaleTransaction(event=event, token_price_usd=float(price), value_usd=value_usd)
        logger.info(
            "whale.detected",
            symbol=event.token_symbol,
            value_usd=round(value_usd, 2),
            direction=event.direction.value,
            tx=event.tx_hash,
        )
        return whale
