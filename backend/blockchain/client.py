"""
Mantle RPC client wrapper.

Thin async-friendly facade over web3.py that:
- Connects to the configured Mantle RPC endpoint.
- Exposes block-number and log-fetch helpers with retry + error handling.
- Resolves ERC-20 metadata (symbol/decimals) with an in-memory cache.

web3.py's HTTP provider is synchronous; calls are wrapped with
``asyncio.to_thread`` so they never block the event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings
from backend.core.logging import get_logger
from backend.core.types import KNOWN_TOKENS

logger = get_logger(__name__)


class MantleClient:
    """Async wrapper around a web3 connection to a Mantle RPC node."""

    def __init__(self, rpc_url: str | None = None) -> None:
        self.rpc_url = rpc_url or settings.MANTLE_RPC_URL
        self._w3: Any | None = None
        self._symbol_cache: dict[str, str] = {}
        self._decimals_cache: dict[str, int] = {}
        # Seed caches from the known-token registry.
        for meta in KNOWN_TOKENS.values():
            addr = str(meta["address"]).lower()
            self._symbol_cache[addr] = str(meta["symbol"])
            self._decimals_cache[addr] = int(meta["decimals"])  # type: ignore[arg-type]

    # ------------------------------------------------------------------ #
    # Connection                                                          #
    # ------------------------------------------------------------------ #
    def _get_w3(self):
        if self._w3 is None:
            from web3 import Web3

            provider = Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 20})
            self._w3 = Web3(provider)
        return self._w3

    async def is_connected(self) -> bool:
        try:
            return await asyncio.to_thread(self._get_w3().is_connected)
        except Exception as exc:  # pragma: no cover - network path
            logger.warning("rpc.connection_check_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------ #
    # Block / log access                                                  #
    # ------------------------------------------------------------------ #
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=5), reraise=True)
    async def get_block_number(self) -> int:
        w3 = self._get_w3()
        return int(await asyncio.to_thread(lambda: w3.eth.block_number))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=5), reraise=True)
    async def get_logs(
        self,
        from_block: int,
        to_block: int,
        topics: list[Any] | None = None,
        address: str | list[str] | None = None,
    ) -> list[dict]:
        """Fetch raw event logs in the given inclusive block range."""
        w3 = self._get_w3()
        params: dict[str, Any] = {"fromBlock": from_block, "toBlock": to_block}
        if topics:
            params["topics"] = topics
        if address:
            params["address"] = address

        def _fetch() -> list[dict]:
            return [dict(log) for log in w3.eth.get_logs(params)]

        return await asyncio.to_thread(_fetch)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=0.5, max=4), reraise=True)
    async def get_block_timestamp(self, block_number: int) -> int:
        w3 = self._get_w3()

        def _fetch() -> int:
            return int(w3.eth.get_block(block_number)["timestamp"])

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------ #
    # ERC-20 metadata (cached)                                            #
    # ------------------------------------------------------------------ #
    async def get_token_decimals(self, address: str) -> int:
        key = address.lower()
        if key in self._decimals_cache:
            return self._decimals_cache[key]
        decimals = await self._call_erc20(address, "decimals", default=18)
        self._decimals_cache[key] = int(decimals)
        return int(decimals)

    async def get_token_symbol(self, address: str) -> str:
        key = address.lower()
        if key in self._symbol_cache:
            return self._symbol_cache[key]
        symbol = await self._call_erc20(address, "symbol", default=key[:8])
        self._symbol_cache[key] = str(symbol)
        return str(symbol)

    async def _call_erc20(self, address: str, fn: str, default: Any) -> Any:
        from backend.blockchain.abi import ERC20_ABI

        try:
            w3 = self._get_w3()

            def _call() -> Any:
                from web3 import Web3

                contract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=ERC20_ABI)
                return getattr(contract.functions, fn)().call()

            return await asyncio.to_thread(_call)
        except Exception as exc:  # unknown / non-standard token
            logger.debug("rpc.erc20_call_failed", address=address, fn=fn, error=str(exc))
            return default


_singleton: MantleClient | None = None


def get_mantle_client() -> MantleClient:
    """Return a process-wide :class:`MantleClient` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = MantleClient()
    return _singleton
