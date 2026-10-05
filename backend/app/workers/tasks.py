"""Celery tasks. Each task runs the shared async job in a fresh event loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run(coro: Any) -> Any:
    async def _wrapped() -> Any:
        from app.db.session import dispose_engine

        try:
            return await coro
        finally:
            # Engines are bound to the loop; dispose so the next task gets a clean pool.
            await dispose_engine()

    return asyncio.run(_wrapped())


@celery_app.task(name="app.workers.tasks.sync_connection", bind=True, max_retries=2)
def sync_connection(self: Any, sync_run_id: str) -> None:
    from app.services.discovery import run_sync_job

    _run(run_sync_job(sync_run_id))


@celery_app.task(name="app.workers.tasks.evaluate_health")
def evaluate_health(organization_id: str | None = None) -> None:
    from app.services.health.evaluator import run_health_job

    _run(run_health_job(organization_id))


@celery_app.task(name="app.workers.tasks.schedule_syncs")
def schedule_syncs() -> int:
    from app.services.scheduling import schedule_due_syncs

    return int(_run(schedule_due_syncs()))
