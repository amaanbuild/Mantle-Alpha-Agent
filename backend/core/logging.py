"""
Structured logging configuration.

Provides JSON-structured logs in production and pretty console logs in
development via ``structlog``. Call :func:`configure_logging` once at process
startup, then obtain loggers with :func:`get_logger`.
"""

from __future__ import annotations

import logging
import sys

import structlog

from backend.config import settings

_configured = False


def configure_logging() -> None:
    """Configure stdlib logging + structlog. Idempotent."""
    global _configured
    if _configured:
        return

    log_level = getattr(logging, settings.LOG_LEVEL, logging.INFO)

    # Route stdlib logging through structlog's formatter.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger, configuring logging lazily on first use."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
