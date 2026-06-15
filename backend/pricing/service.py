"""
Price service: orchestrates cache -> providers -> fallback.

Public API::

    service = get_price_service()
    price = await service.get_price("mETH")        # float USD
    value = await service.value_in_usd("mETH", Decimal("3.5"))

The service is resilient: a failing provider is logged and skipped, never
raising to the caller. If every provider fails and static fallback is disabled,
``get_price`` returns ``None`` and callers must handle a missing price.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.core.logging import get_logger
from backend.core.types import normalize_symbol
from backend.pricing.cache import PriceCache
from backend.pricing.providers import PriceProvider, build_providers

logger = get_logger(__name__)


class PriceService:
    """Caching, fault-tolerant USD price lookups across multiple providers."""

    def __init__(
        self,
        providers: list[PriceProvider] | None = None,
        cache: PriceCache | None = None,
        http_timeout: float = 10.0,
    ) -> None:
        self.providers = providers if providers is not None else build_providers()
        self.cache = cache or PriceCache()
        self._timeout = http_timeout

    async def get_price(self, symbol: str) -> float | None:
        """Return a USD price for ``symbol`` (cached), or ``None`` if unavailable."""
        key = normalize_symbol(symbol)

        cached = await self.cache.get(key)
        if cached is not None:
            return cached

        price = await self._fetch_from_providers(key)
        if price is not None:
            await self.cache.set(key, price)
        else:
            logger.warning("pricing.unavailable", symbol=key)
        return price

    async def value_in_usd(self, symbol: str, amount: Decimal | float) -> float | None:
        """Return ``amount * price`` in USD, or ``None`` if no price is available."""
        price = await self.get_price(symbol)
        if price is None:
            return None
        return float(Decimal(str(price)) * Decimal(str(amount)))

    async def _fetch_from_providers(self, symbol: str) -> float | None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for provider in self.providers:
                try:
                    price = await self._get_with_retry(provider, symbol, client)
                except Exception as exc:
                    logger.warning(
                        "pricing.provider_failed",
                        provider=provider.name,
                        symbol=symbol,
                        error=str(exc),
                    )
                    continue
                if price is not None and price > 0:
                    logger.debug(
                        "pricing.resolved", provider=provider.name, symbol=symbol, price=price
                    )
                    return price
        return None

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.3, max=2),
        reraise=True,
    )
    async def _get_with_retry(
        self, provider: PriceProvider, symbol: str, client: httpx.AsyncClient
    ) -> float | None:
        return await provider.get_price(symbol, client)


_singleton: PriceService | None = None


def get_price_service() -> PriceService:
    """Return a process-wide :class:`PriceService` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = PriceService()
    return _singleton
