"""
Celery application factory and beat schedule.

Celery handles *periodic maintenance and optional polling* (the always-on
real-time monitor lives in ``backend/worker.py``). Tasks are thin sync wrappers
that drive async code via ``asyncio.run``.

Run a worker::      celery -A backend.tasks.celery_app:celery_app worker -l info
Run the beat::      celery -A backend.tasks.celery_app:celery_app beat   -l info
"""

from __future__ import annotations

from celery import Celery

from backend.config import settings

celery_app = Celery(
    "mantle_alpha",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["backend.tasks.monitoring_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=200,
    task_default_retry_delay=10,
    task_time_limit=120,
)

# Periodic schedule. The poll task is optional -- enable it if you prefer
# Celery-driven polling over the dedicated worker loop.
celery_app.conf.beat_schedule = {
    "poll-blocks": {
        "task": "backend.tasks.monitoring_tasks.poll_blocks_task",
        "schedule": float(settings.BLOCK_POLL_INTERVAL),
    },
    "purge-system-logs": {
        "task": "backend.tasks.monitoring_tasks.purge_system_logs_task",
        "schedule": 24 * 60 * 60.0,  # daily
        "kwargs": {"days": 30},
    },
}
