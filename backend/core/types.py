"""
Shared domain types and enumerations.

These enums form the contract between subsystems (AI intent engine, blockchain
monitor, alert engine, bot, API). Keep them stable -- many modules import from
here.
"""

from __future__ import annotations

from enum import Enum


class IntentType(str, Enum):
    """Supported high-level user intents extracted from natural language."""

    CREATE_ALERT = "create_alert"
    DELETE_ALERT = "delete_alert"
    MODIFY_ALERT = "modify_alert"
    LIST_ALERTS = "list_alerts"
    SHOW_HISTORY = "show_history"
    SHOW_STATUS = "show_status"
    HELP = "help"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    """On-chain event categories the system can monitor and alert on."""

    TRANSFER = "transfer"
    SWAP = "swap"
    BUY = "buy"
    SELL = "sell"
    # "any" matches transfers and swaps -- a generic "large activity" rule.
    ANY = "any"


class AlertStatus(str, Enum):
    """Lifecycle status of a generated alert record."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # deduped / below threshold on re-check


class TransactionDirection(str, Enum):
    """Direction of a whale transaction relative to a tracked token."""

    BUY = "buy"
    SELL = "sell"
    TRANSFER = "transfer"
    SWAP = "swap"


# Tokens known to the system out of the box. The price service and event
# normalizer use these for symbol <-> address resolution.
#
# Addresses below are canonical Mantle MAINNET contracts, verified against
# Mantlescan / Blockscout (June 2026). Override or extend at runtime via the
# tracked_tokens table without code changes.
KNOWN_TOKENS: dict[str, dict[str, object]] = {
    "MNT": {
        "symbol": "MNT",
        "name": "Mantle",
        # MNT is the NATIVE gas token on Mantle; this is the WMNT (Wrapped MNT)
        # ERC-20 contract used to observe MNT value flows as Transfer events.
        "address": "0x78c1b0C915c4FAA5FffA6CAbf0219DA63d7f4cb8",
        "decimals": 18,
        "coingecko_id": "mantle",
    },
    "METH": {
        "symbol": "mETH",
        "name": "Mantle Staked Ether",
        # mETH Protocol receipt token (Mantle LSP).
        "address": "0xcDA86A272531e8640cD7F1a92c01839911B90bb0",
        "decimals": 18,
        "coingecko_id": "mantle-staked-ether",
    },
    "WETH": {
        "symbol": "WETH",
        "name": "Wrapped Ether",
        # Mantle BVM_ETH predeploy (bridged WETH).
        "address": "0xdEAddEaDdeadDEadDEADDEAddEADDEAddead1111",
        "decimals": 18,
        "coingecko_id": "weth",
    },
    "USDT": {
        "symbol": "USDT",
        "name": "Tether USD",
        "address": "0x201EBa5CC46D216Ce6DC03F6a759e8E766e956aE",
        "decimals": 6,
        "coingecko_id": "tether",
    },
    "USDC": {
        "symbol": "USDC",
        "name": "USD Coin",
        "address": "0x09Bc4E0D864854c6aFB6eB9A9cdF58aC190D0dF9",
        "decimals": 6,
        "coingecko_id": "usd-coin",
    },
}


def normalize_symbol(symbol: str) -> str:
    """Canonicalize a token symbol for case-insensitive lookups (e.g. 'meth' -> 'METH')."""
    return symbol.strip().upper().lstrip("$")


def resolve_token(symbol: str) -> dict[str, object] | None:
    """Return the known-token metadata for a symbol, or ``None`` if unknown."""
    return KNOWN_TOKENS.get(normalize_symbol(symbol))
