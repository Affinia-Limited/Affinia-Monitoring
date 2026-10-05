"""Celery application. Run with ``celery -A app.workers.celery_app worker --beat``."""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

broker = settings.redis_url or "redis://localhost:6379/0"

celery_app = Celery("monitoring", broker=broker, backend=None, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    task_default_retry_delay=30,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        "schedule-syncs": {
            "task": "app.workers.tasks.schedule_syncs",
            "schedule": settings.sync_interval_minutes * 60,
        },
        "evaluate-health": {
            "task": "app.workers.tasks.evaluate_health",
            "schedule": settings.health_interval_minutes * 60,
        },
    },
)
