"""
Central application configuration.

All configuration is loaded from environment variables (or a local ``.env``
file) via Pydantic Settings. No secret or environment-specific value should
ever be hardcoded elsewhere in the codebase -- import ``settings`` from here.

Usage::

    from backend.config import settings
    print(settings.MANTLE_RPC_URL)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings sourced from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ----------------------------------------------------------------- App
    APP_NAME: str = "Mantle Alpha Agent"
    ENVIRONMENT: str = Field(default="development")  # development | staging | production
    DEBUG: bool = Field(default=True)
    LOG_LEVEL: str = Field(default="INFO")
    API_HOST: str = Field(default="0.0.0.0")
    API_PORT: int = Field(default=8000)
    # Comma-separated list of allowed CORS origins (use "*" for all).
    CORS_ORIGINS: str = Field(default="*")

    # ------------------------------------------------------------ Database
    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/db
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://mantle:mantle@localhost:5432/mantle_alpha"
    )
    DB_POOL_SIZE: int = Field(default=10)
    DB_MAX_OVERFLOW: int = Field(default=20)
    DB_ECHO: bool = Field(default=False)

    # --------------------------------------------------------------- Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/2")

    # ---------------------------------------------------------- Blockchain
    MANTLE_RPC_URL: str = Field(default="https://rpc.mantle.xyz")
    MANTLE_WS_URL: str = Field(default="")  # optional websocket endpoint
    MANTLE_CHAIN_ID: int = Field(default=5000)
    MANTLE_EXPLORER_URL: str = Field(default="https://explorer.mantle.xyz")
    # How many blocks to wait before considering data final.
    BLOCK_CONFIRMATIONS: int = Field(default=1)
    # Seconds between polling for new blocks.
    BLOCK_POLL_INTERVAL: float = Field(default=3.0)
    # Maximum number of blocks to scan in a single batch (back-fill safety).
    MAX_BLOCKS_PER_BATCH: int = Field(default=50)

    # On-chain alert logger contract (optional; logging is skipped if unset).
    ALERT_LOGGER_CONTRACT_ADDRESS: str = Field(default="")
    ALERT_LOGGER_PRIVATE_KEY: str = Field(default="")
    ENABLE_ONCHAIN_LOGGING: bool = Field(default=False)

    # ----------------------------------------------------------------- AI
    # Provider abstraction: "openai" today, others can be added in ai/llm_provider.py
    LLM_PROVIDER: str = Field(default="openai")
    LLM_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_BASE_URL: str = Field(default="")  # optional override for compatible APIs
    LLM_TIMEOUT_SECONDS: float = Field(default=30.0)
    LLM_MAX_RETRIES: int = Field(default=2)
    # If true and no API key is set, fall back to a deterministic rule-based
    # intent parser so the system still runs end-to-end in dev/tests.
    LLM_ALLOW_RULE_FALLBACK: bool = Field(default=True)

    # ------------------------------------------------------------ Telegram
    TELEGRAM_BOT_TOKEN: str = Field(default="")
    # "polling" for local/dev, "webhook" for production.
    TELEGRAM_MODE: str = Field(default="polling")
    TELEGRAM_WEBHOOK_URL: str = Field(default="")
    TELEGRAM_WEBHOOK_SECRET: str = Field(default="")

    # ------------------------------------------------------------- Pricing
    # Comma-separated ordered list of providers to try, e.g. "coingecko,defillama".
    PRICE_PROVIDERS: str = Field(default="coingecko,defillama")
    COINGECKO_API_KEY: str = Field(default="")
    PRICE_CACHE_TTL_SECONDS: int = Field(default=60)
    # Fallback static prices used when every provider fails (dev resilience).
    PRICE_STATIC_FALLBACK_ENABLED: bool = Field(default=True)

    # --------------------------------------------------------------- Rules
    # Default whale threshold applied when a user gives no explicit amount.
    DEFAULT_WHALE_THRESHOLD_USD: float = Field(default=10_000.0)
    MIN_WHALE_THRESHOLD_USD: float = Field(default=100.0)
    MAX_ALERTS_PER_USER: int = Field(default=50)

    # ----------------------------------------------------------- Security
    # Per-user inbound message rate limit (token bucket).
    RATE_LIMIT_MAX_REQUESTS: int = Field(default=20)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60)
    # Optional API key required on REST mutating endpoints (empty disables it).
    API_KEY: str = Field(default="")
    # Max characters accepted from a free-text natural-language message.
    MAX_NL_INPUT_LENGTH: int = Field(default=500)

    # --------------------------------------------------------- Validators
    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Managed hosts (Railway, Render, Heroku, Supabase...) inject a
        # ``postgres://`` or ``postgresql://`` URL, but SQLAlchemy's async engine
        # needs the asyncpg driver. Normalize so a platform-provided DATABASE_URL
        # works out of the box with no manual editing.
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

    @field_validator("ENVIRONMENT")
    @classmethod
    def _normalize_env(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"development", "staging", "production"}:
            raise ValueError(f"Invalid ENVIRONMENT: {v!r}")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        v = v.upper().strip()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in valid:
            raise ValueError(f"Invalid LOG_LEVEL: {v!r}")
        return v

    # ----------------------------------------------------- Derived helpers
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def price_providers_list(self) -> list[str]:
        return [p.strip().lower() for p in self.PRICE_PROVIDERS.split(",") if p.strip()]

    def explorer_tx_url(self, tx_hash: str) -> str:
        """Build a block-explorer URL for a transaction hash."""
        return f"{self.MANTLE_EXPLORER_URL.rstrip('/')}/tx/{tx_hash}"

    def explorer_address_url(self, address: str) -> str:
        """Build a block-explorer URL for an address."""
        return f"{self.MANTLE_EXPLORER_URL.rstrip('/')}/address/{address}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton ``Settings`` instance."""
    return Settings()


# Module-level singleton for convenient imports.
settings: Settings = get_settings()
