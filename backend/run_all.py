"""
All-in-one process: REST API + Telegram bot (polling) + blockchain monitor.

This single ASGI app is designed for free hosting tiers (Render, Koyeb, Fly,
Hugging Face Spaces) that give you exactly one always-on web service. It binds
the platform ``$PORT`` for the REST API and health check, and runs the Telegram
bot and the Mantle block monitor as background tasks inside the same event loop.

Run with::

    uvicorn backend.run_all:app --host 0.0.0.0 --port ${PORT:-8000}

Why one process: the headline feature (real-time whale monitoring) needs an
always-on background loop. Folding it into the web service lets the whole system
run on a single free instance. Keep the instance awake with a free uptime pinger
that hits ``/health`` every few minutes (free web tiers sleep when idle).
"""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import __version__
from backend.api.routes import alerts, health, history, users
from backend.config import settings
from backend.core.logging import configure_logging, get_logger
from backend.database.session import dispose_db, init_db

logger = get_logger(__name__)


async def _smallest_active_threshold() -> float:
    """Minimum threshold across all active rules (monitor gate). Lazy import."""
    from sqlalchemy import func, select

    from backend.database.models import AlertRule
    from backend.database.session import session_scope

    async with session_scope() as session:
        result = await session.execute(
            select(func.min(AlertRule.threshold_usd)).where(AlertRule.is_active.is_(True))
        )
        value = result.scalar_one_or_none()
    return float(value) if value else settings.MIN_WHALE_THRESHOLD_USD


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("run_all.startup", env=settings.ENVIRONMENT, version=__version__)

    # Schema: create_all is idempotent and keeps single-instance free deploys
    # zero-config (no separate migration step needed).
    await init_db()

    tg_app = None
    monitor = None
    monitor_task = None

    # ---- Telegram bot (polling) inside this event loop ----
    if settings.TELEGRAM_BOT_TOKEN:
        from backend.bot.telegram_bot import build_application

        tg_app = build_application()  # also wires the alert engine notifier
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling(allowed_updates=["message"])
        logger.info("run_all.bot_started")
    else:
        logger.warning("run_all.no_telegram_token", note="bot disabled; API/monitor only")

    # ---- Blockchain monitor as a background task ----
    from backend.alerts.engine import get_alert_engine
    from backend.blockchain.monitor import BlockMonitor

    monitor = BlockMonitor(
        on_whale=get_alert_engine().handle_whale,
        min_threshold_provider=_smallest_active_threshold,
    )
    monitor_task = asyncio.create_task(monitor.start())
    logger.info("run_all.monitor_started")

    try:
        yield
    finally:
        if monitor is not None:
            await monitor.stop()
        if monitor_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                monitor_task.cancel()
                await monitor_task
        if tg_app is not None:
            with contextlib.suppress(Exception):
                await tg_app.updater.stop()
                await tg_app.stop()
                await tg_app.shutdown()
        await dispose_db()
        logger.info("run_all.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.APP_NAME} (all-in-one)",
        version=__version__,
        description="REST API + Telegram bot + Mantle monitor in one process.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(alerts.router)
    app.include_router(history.router)
    app.include_router(users.router)

    @app.get("/", tags=["health"], summary="Service banner")
    async def root() -> dict[str, str]:
        return {
            "service": settings.APP_NAME,
            "mode": "all-in-one (api + bot + monitor)",
            "version": __version__,
            "docs": "/docs",
        }

    return app


app = create_app()
