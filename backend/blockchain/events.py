"""
Event decoding & normalization.

Turns raw RPC logs into typed :class:`ChainEvent` objects. Currently decodes:
- ERC-20 ``Transfer(address,address,uint256)``
- UniswapV2-style ``Swap(...)`` (mapped to a generic swap event)

Unknown/garbled logs are skipped (logged at debug). The normalizer resolves
token metadata (symbol/decimals) via :class:`MantleClient` so downstream pricing
and display always have a human symbol.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from backend.blockchain.abi import SWAP_V2_TOPIC, TRANSFER_TOPIC
from backend.blockchain.client import MantleClient
from backend.core.domain import ChainEvent
from backend.core.logging import get_logger
from backend.core.types import EventType, TransactionDirection

logger = get_logger(__name__)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _topic_to_address(topic: object) -> str:
    """Extract a 20-byte address from a 32-byte indexed log topic."""
    hex_str = _to_hex(topic)
    # Last 40 hex chars are the address.
    return "0x" + hex_str[-40:]


def _to_hex(value: object) -> str:
    """Normalize web3 HexBytes / bytes / str into a lowercase 0x hex string."""
    if isinstance(value, bytes):
        return "0x" + value.hex()
    s = str(value)
    if hasattr(value, "hex") and not s.startswith("0x"):
        try:
            return "0x" + value.hex()  # type: ignore[attr-defined]
        except Exception:
            pass
    return s.lower()


def _int_from_data(data: object, slot: int = 0) -> int:
    """Read a 32-byte word (``slot``) from log ``data`` as an integer."""
    hex_str = _to_hex(data)[2:]  # strip 0x
    word = hex_str[slot * 64 : (slot + 1) * 64]
    return int(word, 16) if word else 0


class EventNormalizer:
    """Decodes raw logs into :class:`ChainEvent` objects."""

    def __init__(self, client: MantleClient) -> None:
        self.client = client

    async def normalize_log(
        self, log: dict, block_timestamp: int | None = None
    ) -> ChainEvent | None:
        """Decode a single raw RPC log. Returns ``None`` if not a supported event."""
        topics = log.get("topics") or []
        if not topics:
            return None
        topic0 = _to_hex(topics[0])

        try:
            if topic0 == TRANSFER_TOPIC and len(topics) >= 3:
                return await self._decode_transfer(log, topics)
            if topic0 == SWAP_V2_TOPIC and len(topics) >= 3:
                return await self._decode_swap(log, topics)
        except Exception as exc:  # malformed log -> skip, never crash the monitor
            logger.debug("events.decode_failed", error=str(exc), tx=log.get("transactionHash"))
            return None
        return None

    async def _decode_transfer(self, log: dict, topics: list) -> ChainEvent:
        token_address = _to_hex(log["address"])
        from_addr = _topic_to_address(topics[1])
        to_addr = _topic_to_address(topics[2])
        raw_amount = _int_from_data(log.get("data", "0x"))

        decimals = await self.client.get_token_decimals(token_address)
        symbol = await self.client.get_token_symbol(token_address)
        amount = Decimal(raw_amount) / (Decimal(10) ** decimals)

        # Mint (from zero) reads as a buy-ish inflow; burn (to zero) as a sell-ish outflow.
        direction = TransactionDirection.TRANSFER
        if from_addr.lower() == ZERO_ADDRESS:
            direction = TransactionDirection.BUY
        elif to_addr.lower() == ZERO_ADDRESS:
            direction = TransactionDirection.SELL

        return ChainEvent(
            event_type=EventType.TRANSFER,
            token_symbol=symbol,
            token_address=token_address,
            token_decimals=decimals,
            raw_amount=raw_amount,
            amount=amount,
            from_address=from_addr,
            to_address=to_addr,
            tx_hash=_to_hex(log.get("transactionHash")),
            log_index=int(log.get("logIndex", 0)),
            block_number=int(log.get("blockNumber", 0)),
            direction=direction,
            **_ts_kwargs(block_timestamp_from(log)),
        )

    async def _decode_swap(self, log: dict, topics: list) -> ChainEvent:
        pair_address = _to_hex(log["address"])
        sender = _topic_to_address(topics[1])
        to_addr = _topic_to_address(topics[2])
        amount0_in = _int_from_data(log.get("data", "0x"), 0)
        amount1_in = _int_from_data(log.get("data", "0x"), 1)
        amount0_out = _int_from_data(log.get("data", "0x"), 2)
        amount1_out = _int_from_data(log.get("data", "0x"), 3)

        # We don't know token0/token1 decimals without extra calls; use the
        # larger leg as the headline amount and treat the pair as the token addr.
        raw_amount = max(amount0_in, amount1_in, amount0_out, amount1_out)
        decimals = 18
        amount = Decimal(raw_amount) / (Decimal(10) ** decimals)
        symbol = await self.client.get_token_symbol(pair_address)

        return ChainEvent(
            event_type=EventType.SWAP,
            token_symbol=symbol,
            token_address=pair_address,
            token_decimals=decimals,
            raw_amount=raw_amount,
            amount=amount,
            from_address=sender,
            to_address=to_addr,
            tx_hash=_to_hex(log.get("transactionHash")),
            log_index=int(log.get("logIndex", 0)),
            block_number=int(log.get("blockNumber", 0)),
            direction=TransactionDirection.SWAP,
        )


def block_timestamp_from(log: dict) -> int | None:
    """Best-effort extraction of a block timestamp embedded on a log (if any)."""
    ts = log.get("blockTimestamp")
    if ts is None:
        return None
    try:
        return int(ts, 16) if isinstance(ts, str) else int(ts)
    except (ValueError, TypeError):
        return None


def _ts_kwargs(ts: int | None) -> dict:
    """Build the timestamp kwarg for ChainEvent only when we have a value."""
    if ts is None:
        return {}
    from datetime import datetime

    return {"timestamp": datetime.fromtimestamp(ts, tz=UTC)}
