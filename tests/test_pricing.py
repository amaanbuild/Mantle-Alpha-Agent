"""Tests for the pricing service (offline static-fallback path)."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from backend.pricing.cache import PriceCache
from backend.pricing.providers import StaticFallbackProvider
from backend.pricing.service import PriceService


@pytest.fixture
def service() -> PriceService:
    # Only the static provider -> deterministic, no network.
    return PriceService(providers=[StaticFallbackProvider()], cache=PriceCache(ttl_seconds=60))


async def test_get_price_known_token(service):
    price = await service.get_price("MNT")
    assert price is not None and price > 0


async def test_get_price_case_insensitive(service):
    assert await service.get_price("meth") == await service.get_price("METH")


async def test_value_in_usd(service):
    price = await service.get_price("USDC")
    value = await service.value_in_usd("USDC", Decimal("100"))
    assert value == pytest.approx(price * 100)


async def test_unknown_token_returns_none(service):
    assert await service.get_price("NOPE") is None


async def test_cache_hit(monkeypatch, service):
    await service.get_price("MNT")  # populates cache

    async def _boom(*a, **k):
        raise AssertionError("providers should not be hit on a cache hit")

    monkeypatch.setattr(service, "_fetch_from_providers", _boom)
    assert await service.get_price("MNT") is not None


async def test_provider_failure_is_skipped():
    class Failing(StaticFallbackProvider):
        name = "failing"

        async def get_price(self, symbol, client):  # noqa: ARG002
            raise httpx.ConnectError("down")

    service = PriceService(providers=[Failing(), StaticFallbackProvider()], cache=PriceCache())
    # Falls through the failing provider to the working static one.
    assert await service.get_price("MNT") is not None
