"""
Celery tasks.

- :func:`poll_blocks_task`        : run one monitor poll cycle (optional, an
                                    alternative to the always-on worker loop).
- :func:`purge_system_logs_task`  : housekeeping of the system_logs table.
- :func:`dispatch_whale_task`     : (hook) process a serialized whale candidate
                                    asynchronously, useful for fan-out at scale.

Tasks are sync entrypoints that drive async code via :func:`asyncio.run`.
"""

from __future__ import annotations

import asyncio

from backend.core.logging import get_logger
from backend.database.repositories import SystemLogRepository
from backend.database.session import session_scope
from backend.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="backend.tasks.monitoring_tasks.poll_blocks_task", bind=True, max_retries=3)
def poll_blocks_task(self) -> int:
    """Run a single block-polling cycle and return the number of whales emitted."""
    try:
        return asyncio.run(_poll_once())
    except Exception as exc:  # transient RPC / network -> retry with backoff
        logger.warning("task.poll_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=5) from exc


async def _poll_once() -> int:
    # Imported lazily so importing the task module never spins up a bot/RPC.
    from backend.alerts.engine import get_alert_engine
    from backend.blockchain.monitor import BlockMonitor

    monitor = BlockMonitor(on_whale=get_alert_engine().handle_whale)
    await monitor._init_cursor()  # restore cursor if Redis-backed elsewhere
    return await monitor.poll_once()


@celery_app.task(name="backend.tasks.monitoring_tasks.purge_system_logs_task")
def purge_system_logs_task(days: int = 30) -> int:
    """Delete system_logs rows older than ``days``. Returns rows removed."""
    return asyncio.run(_purge(days))


async def _purge(days: int) -> int:
    async with session_scope() as session:
        removed = await SystemLogRepository(session).purge_older_than(days=days)
    logger.info("task.purged_logs", removed=removed, days=days)
    return removed
