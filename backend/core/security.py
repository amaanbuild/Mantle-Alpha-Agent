"""
Security utilities: rate limiting, input validation, and prompt-injection
hardening.

- :class:`RateLimiter`     : async token-bucket limiter (Redis-backed with an
                             in-memory fallback) keyed per user/IP.
- :func:`sanitize_nl_input`: clamp and clean free-text before it reaches the LLM.
- :func:`looks_like_injection` : heuristic detector for prompt-injection attempts.
- :func:`validate_threshold` / :func:`validate_token_symbol` : domain validation.
"""

from __future__ import annotations

import re
import time

from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
class RateLimiter:
    """
    Sliding-window rate limiter.

    Prefers Redis (shared across processes) but degrades to a per-process
    in-memory window if Redis is unavailable, so the bot never hard-fails on a
    transient Redis outage.
    """

    def __init__(
        self,
        max_requests: int | None = None,
        window_seconds: int | None = None,
        redis_client=None,
    ) -> None:
        self.max_requests = max_requests or settings.RATE_LIMIT_MAX_REQUESTS
        self.window = window_seconds or settings.RATE_LIMIT_WINDOW_SECONDS
        self._redis = redis_client
        self._memory: dict[str, list[float]] = {}

    async def allow(self, key: str) -> bool:
        """Return True if a request for ``key`` is allowed right now."""
        if self._redis is not None:
            try:
                return await self._allow_redis(key)
            except Exception as exc:  # pragma: no cover - resilience path
                logger.warning("ratelimit.redis_failed", error=str(exc))
        return self._allow_memory(key)

    async def _allow_redis(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window
        redis_key = f"ratelimit:{key}"
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, self.window + 1)
        _, _, count, _ = await pipe.execute()
        return int(count) <= self.max_requests

    def _allow_memory(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.window
        bucket = [t for t in self._memory.get(key, []) if t > window_start]
        bucket.append(now)
        self._memory[key] = bucket
        return len(bucket) <= self.max_requests


# --------------------------------------------------------------------------- #
# Input validation & prompt-injection hardening
# --------------------------------------------------------------------------- #

# Phrases commonly used to hijack an LLM's instructions.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+(the\s+)?(system|previous)\s+(prompt|instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"reveal\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"</?(system|assistant|user)>", re.I),
    re.compile(r"act\s+as\s+(a\s+)?(developer|admin|root)", re.I),
]


def looks_like_injection(text: str) -> bool:
    """Heuristically detect prompt-injection attempts in user input."""
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def sanitize_nl_input(text: str) -> str:
    """
    Clamp length, strip control characters, and collapse whitespace before a
    free-text message is embedded into an LLM prompt.
    """
    if text is None:
        return ""
    # Remove non-printable / control characters.
    cleaned = "".join(ch for ch in text if ch.isprintable() or ch in " \t")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[: settings.MAX_NL_INPUT_LENGTH]


_SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")


def validate_token_symbol(symbol: str) -> str:
    """Validate and normalize a token symbol or raise ``ValueError``."""
    if not symbol:
        raise ValueError("Token symbol is required.")
    candidate = symbol.strip().lstrip("$")
    if not _SYMBOL_RE.match(candidate):
        raise ValueError(f"Invalid token symbol: {symbol!r}")
    return candidate.upper()


def validate_threshold(value: float | int | str) -> float:
    """
    Validate a USD threshold against configured bounds.

    Accepts numbers or human strings like ``"10k"``, ``"$50,000"``, ``"1.2m"``.
    """
    threshold = parse_amount(value)
    if threshold < settings.MIN_WHALE_THRESHOLD_USD:
        raise ValueError(f"Threshold must be at least ${settings.MIN_WHALE_THRESHOLD_USD:,.0f}.")
    if threshold > 1_000_000_000:
        raise ValueError("Threshold is unreasonably large.")
    return threshold


_AMOUNT_RE = re.compile(r"^\s*\$?\s*([0-9][0-9,]*\.?[0-9]*)\s*([kKmMbB]?)\s*$")
_SUFFIX_MULT = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def parse_amount(value: float | int | str) -> float:
    """Parse a numeric or shorthand monetary string into a float USD value."""
    if isinstance(value, (int, float)):
        return float(value)
    match = _AMOUNT_RE.match(str(value))
    if not match:
        raise ValueError(f"Could not parse amount: {value!r}")
    number = float(match.group(1).replace(",", ""))
    return number * _SUFFIX_MULT[match.group(2).lower()]
