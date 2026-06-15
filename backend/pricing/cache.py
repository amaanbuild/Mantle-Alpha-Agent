"""
Price cache.

A tiny TTL cache abstraction used by :class:`PriceService`. Uses Redis when a
client is supplied (shared across worker processes) and otherwise an in-process
dict, so pricing works even with no Redis in dev/tests.
"""

from __future__ import annotations

import time

from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class PriceCache:
    """TTL cache for USD prices keyed by normalized symbol."""

    def __init__(self, ttl_seconds: int | None = None, redis_client=None) -> None:
        self.ttl = ttl_seconds or settings.PRICE_CACHE_TTL_SECONDS
        self._redis = redis_client
        self._memory: dict[str, tuple[float, float]] = {}  # symbol -> (price, expires_at)

    async def get(self, symbol: str) -> float | None:
        if self._redis is not None:
            try:
                raw = await self._redis.get(f"price:{symbol}")
                return float(raw) if raw is not None else None
            except Exception as exc:  # pragma: no cover - resilience path
                logger.warning("pricecache.redis_get_failed", error=str(exc))
        entry = self._memory.get(symbol)
        if entry is None:
            return None
        price, expires_at = entry
        if time.time() >= expires_at:
            self._memory.pop(symbol, None)
            return None
        return price

    async def set(self, symbol: str, price: float) -> None:
        if self._redis is not None:
            try:
                await self._redis.set(f"price:{symbol}", price, ex=self.ttl)
                return
            except Exception as exc:  # pragma: no cover - resilience path
                logger.warning("pricecache.redis_set_failed", error=str(exc))
        self._memory[symbol] = (price, time.time() + self.ttl)
