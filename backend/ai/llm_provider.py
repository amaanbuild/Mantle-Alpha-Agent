"""
LLM provider abstraction layer.

The rest of the codebase depends only on :class:`LLMProvider`, never on a
concrete vendor SDK. Swapping OpenAI for another vendor means adding one
subclass and a branch in :func:`get_llm_provider` -- no call sites change.

Two methods are exposed:
- :meth:`complete_json` : returns a parsed dict from a JSON-only completion
                          (used by the intent engine).
- :meth:`complete_text` : returns free-form text (used by the insight generator).
"""

from __future__ import annotations

import abc
import json

from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class LLMError(Exception):
    """Raised when the LLM call fails or returns unusable output."""


class LLMProvider(abc.ABC):
    """Vendor-agnostic chat/completion interface."""

    @property
    @abc.abstractmethod
    def available(self) -> bool:
        """True if the provider is configured and usable (e.g. API key present)."""

    @abc.abstractmethod
    async def complete_json(
        self, system_prompt: str, user_prompt: str, *, temperature: float = 0.0
    ) -> dict:
        """Return a JSON object parsed from the model response."""

    @abc.abstractmethod
    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 160,
    ) -> str:
        """Return free-form text from the model."""


class OpenAIProvider(LLMProvider):
    """OpenAI (and OpenAI-compatible) Chat Completions implementation."""

    def __init__(self) -> None:
        self._client = None  # lazily constructed; keeps import-time cheap
        self._model = settings.LLM_MODEL

    @property
    def available(self) -> bool:
        return bool(settings.OPENAI_API_KEY)

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            kwargs: dict = {
                "api_key": settings.OPENAI_API_KEY,
                "timeout": settings.LLM_TIMEOUT_SECONDS,
                "max_retries": settings.LLM_MAX_RETRIES,
            }
            if settings.OPENAI_BASE_URL:
                kwargs["base_url"] = settings.OPENAI_BASE_URL
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def complete_json(
        self, system_prompt: str, user_prompt: str, *, temperature: float = 0.0
    ) -> dict:
        client = self._get_client()
        try:
            resp = await client.chat.completions.create(
                model=self._model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:  # network / auth / rate-limit
            raise LLMError(f"OpenAI completion failed: {exc}") from exc

        content = (resp.choices[0].message.content or "").strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON: {content!r}") from exc

    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.4,
        max_tokens: int = 160,
    ) -> str:
        client = self._get_client()
        try:
            resp = await client.chat.completions.create(
                model=self._model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise LLMError(f"OpenAI completion failed: {exc}") from exc
        return (resp.choices[0].message.content or "").strip()


_singleton: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return the configured :class:`LLMProvider` singleton."""
    global _singleton
    if _singleton is not None:
        return _singleton

    provider = settings.LLM_PROVIDER.lower()
    if provider == "openai":
        _singleton = OpenAIProvider()
    else:
        # Unknown provider name -> OpenAI-compatible client is the safest default.
        logger.warning("llm.unknown_provider_fallback", provider=provider)
        _singleton = OpenAIProvider()
    return _singleton
