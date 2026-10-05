"""Background job dispatch.

``TASK_BACKEND=celery`` (default) enqueues onto Redis for the worker container.
``TASK_BACKEND=inline`` runs the coroutine as an asyncio task in the API process;
it is only permitted in development/test and exists so the platform can run
without Redis on a developer machine.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from app.core.config import TaskBackend, get_settings

logger = logging.getLogger(__name__)

_inline_tasks: set[asyncio.Task[Any]] = set()


def _run_inline(coro: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)


async def wait_for_inline_jobs() -> None:
    """Test helper: wait for in-process jobs to finish."""
    while _inline_tasks:
        await asyncio.gather(*list(_inline_tasks), return_exceptions=True)


def enqueue_sync(sync_run_id: str) -> None:
    if get_settings().task_backend is TaskBackend.inline:
        from app.services.discovery import run_sync_job

        _run_inline(run_sync_job(sync_run_id))
        return
    from app.workers.tasks import sync_connection

    sync_connection.delay(sync_run_id)


def enqueue_health(organization_id: str) -> None:
    if get_settings().task_backend is TaskBackend.inline:
        from app.services.health.evaluator import run_health_job

        _run_inline(run_health_job(organization_id))
        return
    from app.workers.tasks import evaluate_health

    evaluate_health.delay(organization_id)
