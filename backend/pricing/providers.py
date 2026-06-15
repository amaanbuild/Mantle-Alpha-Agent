"""
Pluggable price providers.

Each provider implements :meth:`PriceProvider.get_price` returning a USD price
for a token symbol, or ``None`` if it cannot serve the request. The
:class:`PriceService` tries them in configured order. Adding a new source is as
simple as subclassing :class:`PriceProvider` and registering it in ``_REGISTRY``.
"""

from __future__ import annotations

import abc

import httpx

from backend.config import settings
from backend.core.logging import get_logger
from backend.core.types import normalize_symbol, resolve_token

logger = get_logger(__name__)

# Reasonable last-resort prices so dev/test environments and total-outage
# scenarios still produce sensible USD valuations. Never used when a live
# provider responds; gated behind PRICE_STATIC_FALLBACK_ENABLED.
STATIC_FALLBACK_PRICES: dict[str, float] = {
    "MNT": 0.65,
    "METH": 3200.0,
    "WETH": 3000.0,
    "USDT": 1.0,
    "USDC": 1.0,
}


class PriceProvider(abc.ABC):
    """Abstract base for a single price source."""

    name: str = "base"

    @abc.abstractmethod
    async def get_price(self, symbol: str, client: httpx.AsyncClient) -> float | None:
        """Return USD price for ``symbol`` or ``None`` if unavailable."""
        raise NotImplementedError


class CoinGeckoProvider(PriceProvider):
    """Prices via the CoinGecko simple-price API (uses each token's coingecko_id)."""

    name = "coingecko"
    BASE_URL = "https://api.coingecko.com/api/v3/simple/price"

    async def get_price(self, symbol: str, client: httpx.AsyncClient) -> float | None:
        meta = resolve_token(symbol)
        coingecko_id = meta.get("coingecko_id") if meta else None
        if not coingecko_id:
            return None
        params = {"ids": coingecko_id, "vs_currencies": "usd"}
        headers = {}
        if settings.COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = settings.COINGECKO_API_KEY
        resp = await client.get(self.BASE_URL, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        price = data.get(str(coingecko_id), {}).get("usd")
        return float(price) if price is not None else None


class DefiLlamaProvider(PriceProvider):
    """Prices via DeFiLlama's coins API keyed by chain:address (no API key needed)."""

    name = "defillama"
    BASE_URL = "https://coins.llama.fi/prices/current"
    CHAIN = "mantle"

    async def get_price(self, symbol: str, client: httpx.AsyncClient) -> float | None:
        meta = resolve_token(symbol)
        address = meta.get("address") if meta else None
        if not address:
            return None
        coin_key = f"{self.CHAIN}:{address}"
        resp = await client.get(f"{self.BASE_URL}/{coin_key}")
        resp.raise_for_status()
        data = resp.json()
        entry = data.get("coins", {}).get(coin_key)
        if not entry:
            return None
        price = entry.get("price")
        return float(price) if price is not None else None


class StaticFallbackProvider(PriceProvider):
    """Deterministic last-resort prices (resilience / offline dev / tests)."""

    name = "static"

    async def get_price(self, symbol: str, client: httpx.AsyncClient) -> float | None:
        if not settings.PRICE_STATIC_FALLBACK_ENABLED:
            return None
        return STATIC_FALLBACK_PRICES.get(normalize_symbol(symbol))


_REGISTRY: dict[str, type[PriceProvider]] = {
    CoinGeckoProvider.name: CoinGeckoProvider,
    DefiLlamaProvider.name: DefiLlamaProvider,
    StaticFallbackProvider.name: StaticFallbackProvider,
}


def build_providers() -> list[PriceProvider]:
    """Instantiate providers in the order configured by ``PRICE_PROVIDERS``.

    The static fallback is always appended last (when enabled) so a live source
    is always preferred over a hardcoded price.
    """
    providers: list[PriceProvider] = []
    for name in settings.price_providers_list:
        cls = _REGISTRY.get(name)
        if cls is None:
            logger.warning("pricing.unknown_provider", provider=name)
            continue
        providers.append(cls())
    if settings.PRICE_STATIC_FALLBACK_ENABLED:
        providers.append(StaticFallbackProvider())
    return providers
