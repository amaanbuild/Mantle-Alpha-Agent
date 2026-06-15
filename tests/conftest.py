"""
Pytest fixtures and test harness.

Configures the whole backend to run against an in-memory SQLite database (shared
via ``StaticPool``) and offline pricing/LLM, so the suite needs no Postgres,
Redis, RPC node, OpenAI key, or Telegram token. Environment variables are set
BEFORE any backend module is imported so the cached ``settings`` singleton picks
them up.
"""

from __future__ import annotations

import os

# --- Configure the environment before importing backend modules. -----------
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("OPENAI_API_KEY", "")  # force rule-based fallback
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")
os.environ.setdefault("PRICE_PROVIDERS", "static")  # no network calls
os.environ.setdefault("PRICE_STATIC_FALLBACK_ENABLED", "true")
os.environ.setdefault("LLM_ALLOW_RULE_FALLBACK", "true")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import backend.database.session as session_module  # noqa: E402
import pytest_asyncio  # noqa: E402
from backend.database.models import Base  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """A fresh in-memory SQLite engine per test, patched into the app globals."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # Patch the module globals so session_scope() / get_session() use this engine.
    orig_engine = session_module.engine
    orig_maker = session_module.AsyncSessionLocal
    session_module.engine = engine
    session_module.AsyncSessionLocal = test_sessionmaker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()
        session_module.engine = orig_engine
        session_module.AsyncSessionLocal = orig_maker


@pytest_asyncio.fixture
async def session(db_engine):
    """A committing session for arranging/asserting test data."""
    async with session_module.AsyncSessionLocal() as s:
        yield s


@pytest_asyncio.fixture
async def user(session):
    """A persisted test user."""
    from backend.database.repositories import UserRepository

    repo = UserRepository(session)
    u = await repo.get_or_create(telegram_id=12345, chat_id=12345, username="tester")
    await session.commit()
    return u
