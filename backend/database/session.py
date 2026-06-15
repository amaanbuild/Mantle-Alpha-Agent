"""
Async database engine and session management.

Exposes:
- ``engine``                : the process-wide AsyncEngine.
- ``AsyncSessionLocal``     : async sessionmaker.
- :func:`get_session`       : FastAPI dependency yielding a session.
- :func:`session_scope`     : async context manager for non-request code
                              (Celery tasks, monitor loop, bot handlers).
- :func:`init_db` / :func:`dispose_db` : lifecycle helpers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings
from backend.core.logging import get_logger
from backend.database.models import Base

logger = get_logger(__name__)


def _build_engine() -> AsyncEngine:
    """Create the async engine, adapting pool args for SQLite (tests)."""
    url = settings.DATABASE_URL
    # SQLite (used in tests) does not support pool sizing arguments.
    if url.startswith("sqlite"):
        return create_async_engine(url, echo=settings.DB_ECHO, future=True)
    return create_async_engine(
        url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,  # recover gracefully from dropped connections
        future=True,
    )


engine: AsyncEngine = _build_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session and guarantees cleanup."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """
    Transactional scope for non-request code paths.

    Commits on success, rolls back on error, always closes::

        async with session_scope() as session:
            session.add(obj)
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Create all tables (used in dev/tests; production uses Alembic)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database.initialized", url=_safe_url())


async def dispose_db() -> None:
    """Dispose of the engine connection pool on shutdown."""
    await engine.dispose()
    logger.info("database.disposed")


def _safe_url() -> str:
    """Return the DB URL with credentials redacted for logging."""
    url = settings.DATABASE_URL
    if "@" in url:
        scheme, rest = url.split("://", 1)
        _, host = rest.split("@", 1)
        return f"{scheme}://***@{host}"
    return url
