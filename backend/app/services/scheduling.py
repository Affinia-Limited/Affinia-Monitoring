"""Periodic synchronisation scheduling."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.db.session import session_scope
from app.models import AzureConnection
from app.services.discovery import queue_sync_run
from app.services.jobs import enqueue_sync

logger = logging.getLogger(__name__)


async def schedule_due_syncs() -> int:
    """Queue a scheduled sync for every enabled connection without one in flight."""
    queued: list[str] = []
    async with session_scope() as db:
        connections = list(
            await db.scalars(
                select(AzureConnection).where(
                    AzureConnection.deleted_at.is_(None),
                    AzureConnection.sync_enabled.is_(True),
                    AzureConnection.status != "disabled",
                )
            )
        )
        for connection in connections:
            run, created = await queue_sync_run(db, connection, "scheduled")
            if created:
                queued.append(str(run.id))
    for run_id in queued:
        enqueue_sync(run_id)
    logger.info("scheduled_syncs", extra={"count": len(queued)})
    return len(queued)
