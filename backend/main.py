"""
FastAPI application entrypoint.

Exposes the REST API and OpenAPI docs. Database schema is managed by Alembic in
production; in non-production environments tables are auto-created on startup
for convenience. The blockchain monitor and Telegram bot run as SEPARATE
processes (see ``backend/worker.py`` and ``backend/bot/telegram_bot.py``) so the
API stays stateless and horizontally scalable.

Run with::

    uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import __version__
from backend.api.routes import alerts, health, history, users
from backend.config import settings
from backend.core.logging import configure_logging, get_logger
from backend.database.session import dispose_db, init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("api.startup", env=settings.ENVIRONMENT, version=__version__)
    if not settings.is_production:
        # Convenience for dev/test; production uses `alembic upgrade head`.
        await init_db()
    yield
    await dispose_db()
    logger.info("api.shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        description=(
            "AI-powered Mantle blockchain whale-alert agent. "
            "Create alert rules, browse history, and check system health."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
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
        return {"service": settings.APP_NAME, "version": __version__, "docs": "/docs"}

    return app


app = create_app()
