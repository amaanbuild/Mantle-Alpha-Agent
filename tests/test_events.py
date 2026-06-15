"""Tests for raw-log decoding / event normalization."""

from __future__ import annotations

from decimal import Decimal

import pytest
from backend.blockchain.abi import TRANSFER_TOPIC
from backend.blockchain.events import EventNormalizer
from backend.core.types import EventType, TransactionDirection


class _StubClient:
    async def get_token_decimals(self, address: str) -> int:  # noqa: ARG002
        return 18

    async def get_token_symbol(self, address: str) -> str:  # noqa: ARG002
        return "mETH"


def _addr_topic(addr_hex: str) -> str:
    """Left-pad a 20-byte address into a 32-byte topic."""
    return "0x" + addr_hex.lower().replace("0x", "").rjust(64, "0")


def _amount_data(tokens: str, decimals: int = 18) -> str:
    raw = int(Decimal(tokens) * (10**decimals))
    return "0x" + f"{raw:064x}"


@pytest.fixture
def normalizer() -> EventNormalizer:
    return EventNormalizer(_StubClient())


async def test_decode_transfer(normalizer):
    log = {
        "topics": [
            TRANSFER_TOPIC,
            _addr_topic("0x1111111111111111111111111111111111111111"),
            _addr_topic("0x2222222222222222222222222222222222222222"),
        ],
        "data": _amount_data("5"),
        "address": "0xcDA86A272531e8640cD7F1a92c01839911B90bb0",
        "transactionHash": "0x" + "a" * 64,
        "logIndex": 2,
        "blockNumber": 1000,
    }
    event = await normalizer.normalize_log(log)
    assert event is not None
    assert event.event_type == EventType.TRANSFER
    assert event.token_symbol == "mETH"
    assert event.amount == Decimal("5")
    assert event.from_address.endswith("1111")
    assert event.to_address.endswith("2222")
    assert event.log_index == 2


async def test_mint_is_buy(normalizer):
    log = {
        "topics": [
            TRANSFER_TOPIC,
            _addr_topic("0x0000000000000000000000000000000000000000"),
            _addr_topic("0x2222222222222222222222222222222222222222"),
        ],
        "data": _amount_data("10"),
        "address": "0xcDA86A272531e8640cD7F1a92c01839911B90bb0",
        "transactionHash": "0x" + "b" * 64,
        "logIndex": 0,
        "blockNumber": 1001,
    }
    event = await normalizer.normalize_log(log)
    assert event.direction == TransactionDirection.BUY


async def test_unknown_topic_skipped(normalizer):
    log = {"topics": ["0x" + "f" * 64], "data": "0x", "address": "0xabc"}
    assert await normalizer.normalize_log(log) is None


async def test_empty_topics_skipped(normalizer):
    assert await normalizer.normalize_log({"topics": []}) is None
