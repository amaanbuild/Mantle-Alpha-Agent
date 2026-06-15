"""
AI insight generator.

Given a priced :class:`WhaleTransaction` (and optional recent-average context),
produce a concise (<50 word) natural-language insight for the alert message.

Falls back to a deterministic template when the LLM is unavailable, so every
alert always carries a sensible insight.
"""

from __future__ import annotations

from backend.ai.llm_provider import LLMError, LLMProvider, get_llm_provider
from backend.core.domain import WhaleTransaction
from backend.core.logging import get_logger
from backend.core.types import TransactionDirection

logger = get_logger(__name__)


SYSTEM_PROMPT = """You are a crypto on-chain analyst. Given a single whale \
transaction on the Mantle network, write ONE concise insight (max 45 words, no \
preamble, no markdown headers). Be factual and measured. If a comparison to the \
recent average is provided, reference it (e.g. "4.2x larger than the 24h average"). \
Do not give financial advice. Do not invent data not provided."""


class InsightGenerator:
    """Produces short analyst-style insights for whale alerts."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm or get_llm_provider()

    async def generate(self, whale: WhaleTransaction, avg_value_usd: float | None = None) -> str:
        """Return a <50 word insight string for a whale transaction."""
        if self._llm.available:
            try:
                prompt = self._build_prompt(whale, avg_value_usd)
                text = await self._llm.complete_text(SYSTEM_PROMPT, prompt, max_tokens=110)
                if text:
                    return self._clamp_words(text, 50)
            except LLMError as exc:
                logger.warning("insight.llm_failed_fallback", error=str(exc))
        return self._template(whale, avg_value_usd)

    def _build_prompt(self, whale: WhaleTransaction, avg: float | None) -> str:
        e = whale.event
        lines = [
            f"Token: {e.token_symbol}",
            f"Action: {e.direction.value}",
            f"Amount: {e.amount} {e.token_symbol}",
            f"USD value: ${whale.value_usd:,.0f}",
            f"From: {whale.short_from}",
            f"To: {whale.short_to}",
        ]
        if avg and avg > 0:
            ratio = whale.value_usd / avg
            lines.append(f"Recent 24h average transfer: ${avg:,.0f} ({ratio:.1f}x)")
        return "\n".join(lines)

    def _template(self, whale: WhaleTransaction, avg: float | None) -> str:
        """Deterministic fallback insight."""
        e = whale.event
        action = {
            TransactionDirection.BUY: "accumulated",
            TransactionDirection.SELL: "offloaded",
            TransactionDirection.SWAP: "swapped",
            TransactionDirection.TRANSFER: "moved",
        }.get(e.direction, "moved")
        base = f"A wallet {action} ${whale.value_usd:,.0f} of {e.token_symbol}."
        if avg and avg > 0:
            ratio = whale.value_usd / avg
            if ratio >= 1.5:
                base += (
                    f" That's {ratio:.1f}x the recent average transfer size, "
                    "which may signal notable positioning."
                )
        return self._clamp_words(base, 50)

    @staticmethod
    def _clamp_words(text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text.strip()
        return " ".join(words[:max_words]).rstrip(".,") + "…"


_singleton: InsightGenerator | None = None


def get_insight_generator() -> InsightGenerator:
    """Return a process-wide :class:`InsightGenerator` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = InsightGenerator()
    return _singleton
