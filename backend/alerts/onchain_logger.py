"""
On-chain alert logger client.

Optionally records an immutable fingerprint of each alert to the ``AlertLogger``
Solidity contract on Mantle (see ``contracts/AlertLogger.sol``). Gated behind
``ENABLE_ONCHAIN_LOGGING``; when disabled (the default) all methods are no-ops so
the core pipeline never depends on having a funded key.
"""

from __future__ import annotations

import asyncio

from backend.config import settings
from backend.core.domain import WhaleTransaction
from backend.core.logging import get_logger

logger = get_logger(__name__)

# Minimal ABI matching AlertLogger.logAlert(...).
ALERT_LOGGER_ABI = [
    {
        "inputs": [
            {"name": "alertHash", "type": "bytes32"},
            {"name": "token", "type": "string"},
            {"name": "amountUsd", "type": "uint256"},
            {"name": "txHash", "type": "bytes32"},
        ],
        "name": "logAlert",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


class OnChainLogger:
    """Writes alert fingerprints to the AlertLogger contract (best-effort)."""

    def __init__(self) -> None:
        self.enabled = (
            settings.ENABLE_ONCHAIN_LOGGING
            and bool(settings.ALERT_LOGGER_CONTRACT_ADDRESS)
            and bool(settings.ALERT_LOGGER_PRIVATE_KEY)
        )
        self._w3 = None
        self._account = None
        self._contract = None

    def _ensure_ready(self) -> bool:
        if not self.enabled:
            return False
        if self._contract is not None:
            return True
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(settings.MANTLE_RPC_URL, request_kwargs={"timeout": 20}))
            account = w3.eth.account.from_key(settings.ALERT_LOGGER_PRIVATE_KEY)
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(settings.ALERT_LOGGER_CONTRACT_ADDRESS),
                abi=ALERT_LOGGER_ABI,
            )
            self._w3, self._account, self._contract = w3, account, contract
            return True
        except Exception as exc:  # pragma: no cover - requires funded key
            logger.error("onchain.init_failed", error=str(exc))
            self.enabled = False
            return False

    async def log_alert(self, whale: WhaleTransaction) -> str | None:
        """Submit a logAlert tx. Returns the tx hash, or ``None`` if disabled/failed."""
        if not self._ensure_ready():
            return None
        return await asyncio.to_thread(self._send, whale)

    def _send(self, whale: WhaleTransaction) -> str | None:  # pragma: no cover - on-chain
        from web3 import Web3

        try:
            w3, account, contract = self._w3, self._account, self._contract
            alert_hash = bytes.fromhex(whale.dedup_key.ljust(64, "0")[:64])
            tx_hash_bytes = _to_bytes32(whale.event.tx_hash)
            fn = contract.functions.logAlert(
                alert_hash,
                whale.event.token_symbol,
                int(whale.value_usd),
                tx_hash_bytes,
            )
            tx = fn.build_transaction(
                {
                    "from": account.address,
                    "nonce": w3.eth.get_transaction_count(account.address),
                    "chainId": settings.MANTLE_CHAIN_ID,
                    "gas": 200_000,
                    "gasPrice": w3.eth.gas_price,
                }
            )
            signed = account.sign_transaction(tx)
            receipt_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hex = Web3.to_hex(receipt_hash)
            logger.info("onchain.logged", tx=tx_hex, alert=whale.dedup_key)
            return tx_hex
        except Exception as exc:
            logger.error("onchain.log_failed", error=str(exc))
            return None


def _to_bytes32(hexstr: str) -> bytes:
    raw = hexstr[2:] if hexstr.startswith("0x") else hexstr
    return bytes.fromhex(raw.rjust(64, "0")[:64])


_singleton: OnChainLogger | None = None


def get_onchain_logger() -> OnChainLogger:
    global _singleton
    if _singleton is None:
        _singleton = OnChainLogger()
    return _singleton
