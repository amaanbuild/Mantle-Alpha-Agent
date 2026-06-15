"""
Blockchain monitor worker (long-running process).

Wires the full real-time pipeline:

    Mantle RPC ──> BlockMonitor ──> WhaleDetector ──> AlertEngine ──> Telegram

Run as its own process/container::

    python -m backend.worker

It creates a send-only Telegram ``Bot`` (no polling) to deliver alerts, attaches
it to the shared :class:`AlertEngine`, and starts the :class:`BlockMonitor`. The
monitor's whale gate self-tunes to the smallest active rule threshold.
"""

from __future__ import annotations

import asyncio
import contextlib

from sqlalchemy import func, select

from backend.alerts.engine import get_alert_engine
from backend.blockchain.monitor import BlockMonitor
from backend.config import settings
from backend.core.logging import configure_logging, get_logger
from backend.database.models import AlertRule
from backend.database.session import dispose_db, init_db, session_scope

logger = get_logger(__name__)


async def _smallest_active_threshold() -> float:
    """Return the minimum threshold across all active rules (monitor gate)."""
    async with session_scope() as session:
        result = await session.execute(
            select(func.min(AlertRule.threshold_usd)).where(AlertRule.is_active.is_(True))
        )
        value = result.scalar_one_or_none()
    return float(value) if value else settings.MIN_WHALE_THRESHOLD_USD


def _build_notifier():
    """Create a send-only Telegram notifier, or ``None`` if no token configured."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("worker.no_telegram_token", note="alerts will not be delivered")
        return None
    from telegram import Bot

    from backend.bot.telegram_bot import TelegramNotifier

    return TelegramNotifier(Bot(token=settings.TELEGRAM_BOT_TOKEN)).send


async def _maybe_redis():
    """Optional Redis client for cursor persistence (None on failure)."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:  # pragma: no cover - resilience path
        logger.warning("worker.redis_unavailable", error=str(exc))
        return None


async def main() -> None:
    configure_logging()
    logger.info("worker.starting")

    if not settings.is_production:
        await init_db()

    engine = get_alert_engine()
    notifier = _build_notifier()
    if notifier is not None:
        engine.set_notifier(notifier)

    redis_client = await _maybe_redis()

    monitor = BlockMonitor(
        on_whale=engine.handle_whale,
        min_threshold_provider=_smallest_active_threshold,
        redis_client=redis_client,
    )

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    # Graceful shutdown on SIGINT/SIGTERM (POSIX); Windows falls back to KeyboardInterrupt.
    with contextlib.suppress(NotImplementedError):
        import signal

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)

    monitor_task = asyncio.create_task(monitor.start())
    try:
        await stop.wait()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        await monitor.stop()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        if redis_client is not None:
            await redis_client.aclose()
        await dispose_db()
        logger.info("worker.stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
