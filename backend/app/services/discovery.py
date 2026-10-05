"""Resource discovery and synchronisation.

A sync run for one Azure connection:

1. verifies each subscription is readable by the platform identity
2. verifies Resource Graph read permission
3. discovers resource groups and resources via Resource Graph
4. upserts by lower-cased ARM id (never duplicates), resurrects resources that
   reappear and marks resources no longer in Azure as deleted
5. categorises each resource (monitor plugin) and assigns project/environment
   from tags or the connection defaults (manual assignments are preserved)
6. generates/updates dashboards from templates
7. evaluates health

Progress is persisted after every step so the UI can show it live.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.metrics import JOB_FAILURES, JOB_RUNS, SYNC_FAILURES
from app.db.session import session_scope
from app.models import AzureConnection, Environment, Project, Resource, ResourceGroup, Subscription, SyncRun
from app.services.azure.provider import get_azure_services
from app.services.azure.types import AzureServices, DiscoveredResource
from app.services.monitors.registry import resolve_monitor

logger = logging.getLogger(__name__)

STEPS: list[tuple[str, str]] = [
    ("authenticate", "Authenticate to Azure"),
    ("subscriptions", "Verify subscriptions"),
    ("permissions", "Verify read permissions"),
    ("discover", "Discover resources"),
    ("categorise", "Categorise and assign resources"),
    ("dashboards", "Apply dashboard templates"),
    ("health", "Evaluate health"),
]

ENVIRONMENT_ALIASES: dict[str, set[str]] = {
    "development": {"dev", "development", "develop", "dv"},
    "uat": {"uat", "test", "tst", "qa", "acceptance"},
    "staging": {"stg", "staging", "stage", "preprod", "pre-prod"},
    "production": {"prod", "production", "prd", "live", "prod01"},
}

STALE_RUN_AFTER = timedelta(hours=1)


def now_utc() -> datetime:
    return datetime.now(UTC)


def new_steps() -> list[dict[str, Any]]:
    return [{"key": k, "label": label, "status": "pending", "detail": None} for k, label in STEPS]


def _fold(value: str | None) -> str:
    return (value or "").strip().casefold()


def _tag_lookup(tags: dict[str, str], keys: Iterable[str]) -> str | None:
    lowered = {_fold(k): v for k, v in tags.items()}
    for key in keys:
        value = lowered.get(_fold(key))
        if value:
            return str(value)
    return None


def project_matches(project: Project, value: str) -> bool:
    v = _fold(value)
    return v in {_fold(project.slug), _fold(project.name)} | {_fold(t) for t in project.tag_values or []}


def environment_matches(env: Environment, value: str) -> bool:
    v = _fold(value)
    names = {_fold(env.slug), _fold(env.name)} | {_fold(t) for t in env.tag_values or []}
    return v in names or v in ENVIRONMENT_ALIASES.get(env.kind, set())


_NAME_SPLIT = re.compile(r"[^a-z0-9]+")


def name_tokens(*names: str | None) -> list[set[str]]:
    """Words of each name, e.g. ``app-crm-prod-uks`` -> {app, crm, prod, uks}. Empty names are skipped."""
    return [{t for t in _NAME_SPLIT.split(_fold(n)) if t} for n in names if n]


def _unique(matches: list[Any]) -> Any | None:
    return matches[0] if len(matches) == 1 else None


def project_from_names(projects: list[Project], token_sets: list[set[str]]) -> Project | None:
    """The single project named by a whole word of the resource name (or, failing that, its resource group).

    Words must equal the project's slug, name or a tag value exactly: ``crm`` matches ``app-crm-prod-uks``
    but not ``crmlando``. Ambiguous names (two projects) match nothing.
    """
    for tokens in token_sets:
        found = _unique([p for p in projects if any(project_matches(p, t) for t in tokens)])
        if found is not None:
            return found
    return None


def environment_from_names(envs: list[Environment], token_sets: list[set[str]]) -> Environment | None:
    for tokens in token_sets:
        found = _unique([e for e in envs if any(environment_matches(e, t) for t in tokens)])
        if found is not None:
            return found
    return None


def assign(
    tags: dict[str, str],
    projects: list[Project],
    environments_by_project: dict[uuid.UUID, list[Environment]],
    default_project_id: uuid.UUID | None,
    default_environment_id: uuid.UUID | None,
    resource_name: str | None = None,
    resource_group: str | None = None,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str]:
    """Project/environment for a resource. Precedence: tags, then naming convention, then connection defaults.

    The naming convention reads whole words of the resource name, then of its resource group
    (``rg-prism-dev-uks``), so resources such as ``acrprismdevuks`` are still placed by their group.
    """
    settings = get_settings()
    project_value = _tag_lookup(tags, settings.project_tag_keys)
    env_value = _tag_lookup(tags, settings.environment_tag_keys)
    tokens = name_tokens(resource_name, resource_group)

    project = next((p for p in projects if project_value and project_matches(p, project_value)), None)
    source = "tag" if project else "none"
    if project is None:
        project = project_from_names(projects, tokens)
        source = "name" if project else "none"
    if project is None and default_project_id:
        project = next((p for p in projects if p.id == default_project_id), None)
        source = "connection_default" if project else "none"
    if project is None:
        return None, None, "none"

    envs = environments_by_project.get(project.id, [])
    env = next((e for e in envs if env_value and environment_matches(e, env_value)), None)
    if env is None:
        env = environment_from_names(envs, tokens)
    if env is None and default_environment_id:
        env = next((e for e in envs if e.id == default_environment_id), None)
    return project.id, env.id if env else None, source


class SyncProgress:
    def __init__(self, db: AsyncSession, run: SyncRun):
        self.db = db
        self.run = run

    async def _save(self) -> None:
        # JSON columns are not mutation-tracked; flag the change explicitly.
        flag_modified(self.run, "steps")
        await self.db.commit()

    async def start(self, key: str) -> None:
        for step in self.run.steps:
            if step["key"] == key:
                step.update(status="running", started_at=now_utc().isoformat())
        await self._save()

    async def finish(self, key: str, detail: str | None = None, status: str = "succeeded") -> None:
        for step in self.run.steps:
            if step["key"] == key:
                step.update(status=status, detail=detail, finished_at=now_utc().isoformat())
        await self._save()

    async def fail_remaining(self, key: str, message: str) -> None:
        failed = False
        for step in self.run.steps:
            if step["key"] == key:
                step.update(status="failed", detail=message, finished_at=now_utc().isoformat())
                failed = True
            elif failed and step["status"] == "pending":
                step["status"] = "skipped"
        await self._save()


async def _upsert(
    db: AsyncSession,
    connection: AzureConnection,
    subscriptions: dict[str, Subscription],
    discovered_groups: list[Any],
    discovered: list[DiscoveredResource],
) -> dict[str, int]:
    seen_at = now_utc()
    stats = {"discovered": len(discovered), "created": 0, "updated": 0, "removed": 0, "restored": 0, "unsupported": 0}

    # Resource groups
    existing_groups = {
        g.azure_id: g
        for g in await db.scalars(
            select(ResourceGroup).where(
                ResourceGroup.organization_id == connection.organization_id,
                ResourceGroup.subscription_ref_id.in_([s.id for s in subscriptions.values()]),
            )
        )
    }
    group_ids: dict[tuple[str, str], ResourceGroup] = {}
    seen_groups: set[str] = set()
    for g in discovered_groups:
        sub = subscriptions.get(g.subscription_id.lower())
        if sub is None:
            continue
        group_row = existing_groups.get(g.azure_id)
        if group_row is None:
            group_row = ResourceGroup(
                organization_id=connection.organization_id, subscription_ref_id=sub.id, azure_id=g.azure_id
            )
            db.add(group_row)
            existing_groups[g.azure_id] = group_row
        group_row.name, group_row.location, group_row.tags, group_row.last_seen_at, group_row.deleted_at = (
            g.name,
            g.location,
            g.tags,
            seen_at,
            None,
        )
        seen_groups.add(g.azure_id)
        group_ids[(g.subscription_id.lower(), g.name.lower())] = group_row
    for group_azure_id, group_row in existing_groups.items():
        if group_azure_id not in seen_groups and group_row.deleted_at is None:
            group_row.deleted_at = seen_at
    await db.flush()

    projects = list(
        await db.scalars(
            select(Project).where(Project.organization_id == connection.organization_id, Project.deleted_at.is_(None))
        )
    )
    envs_by_project: dict[uuid.UUID, list[Environment]] = {}
    for env in await db.scalars(
        select(Environment).where(
            Environment.organization_id == connection.organization_id, Environment.deleted_at.is_(None)
        )
    ):
        envs_by_project.setdefault(env.project_id, []).append(env)

    existing = {
        r.azure_id: r
        for r in await db.scalars(
            select(Resource).where(
                Resource.organization_id == connection.organization_id,
                Resource.subscription_ref_id.in_([s.id for s in subscriptions.values()]),
            )
        )
    }
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for item in discovered:
        sub = subscriptions.get(item.subscription_id.lower())
        if sub is None:
            continue
        seen.add(item.azure_id)
        counts[sub.subscription_id] = counts.get(sub.subscription_id, 0) + 1
        monitor = resolve_monitor(item.resource_type, item.kind, item.sku)
        if monitor.key == "generic":
            stats["unsupported"] += 1
        row = existing.get(item.azure_id)
        if row is None:
            row = Resource(
                organization_id=connection.organization_id,
                connection_id=connection.id,
                subscription_ref_id=sub.id,
                azure_id=item.azure_id,
                first_seen_at=seen_at,
            )
            db.add(row)
            existing[item.azure_id] = row
            stats["created"] += 1
        elif row.deleted_at is not None:
            row.deleted_at = None
            stats["restored"] += 1
        else:
            stats["updated"] += 1

        group = group_ids.get((item.subscription_id.lower(), item.resource_group.lower()))
        row.connection_id = connection.id
        row.resource_group_id = group.id if group else None
        row.name = item.name
        row.resource_type = item.resource_type
        row.kind = item.kind
        row.sku = item.sku
        row.location = item.location
        row.subscription_id = item.subscription_id.lower()
        row.resource_group = item.resource_group
        row.tags = item.tags
        row.properties = item.properties
        row.monitor_key = monitor.key
        row.last_seen_at = seen_at

        if row.assignment_source != "manual":
            merged_tags = {**(group.tags if group else {}), **item.tags}
            project_id, env_id, source = assign(
                merged_tags,
                projects,
                envs_by_project,
                connection.default_project_id,
                connection.default_environment_id,
                resource_name=item.name,
                resource_group=item.resource_group,
            )
            row.project_id, row.environment_id, row.assignment_source = project_id, env_id, source

    for azure_id, row in existing.items():
        if azure_id not in seen and row.deleted_at is None:
            row.deleted_at = seen_at
            stats["removed"] += 1

    for sub in subscriptions.values():
        sub.resource_count = counts.get(sub.subscription_id, 0)
        sub.last_synced_at = seen_at
    await db.flush()
    return stats


async def execute_sync(db: AsyncSession, run: SyncRun, azure: AzureServices) -> None:
    from app.services.dashboards.generator import generate_dashboards
    from app.services.health.evaluator import evaluate_resources

    progress = SyncProgress(db, run)
    connection = await db.get(AzureConnection, run.connection_id)
    if connection is None or connection.deleted_at is not None:
        run.status, run.error_code, run.finished_at = "failed", "CONNECTION_NOT_FOUND", now_utc()
        await db.commit()
        return

    run.status, run.started_at = "running", now_utc()
    await db.commit()
    current = "authenticate"
    try:
        subscriptions = {
            s.subscription_id.lower(): s
            for s in await db.scalars(
                select(Subscription).where(
                    Subscription.connection_id == connection.id, Subscription.deleted_at.is_(None)
                )
            )
        }
        await progress.start(current)
        await progress.finish(current, "Using the platform identity" + (" (demo data)" if azure.is_mock else ""))

        current = "subscriptions"
        await progress.start(current)
        for sub in subscriptions.values():
            info = await azure.resource_graph.get_subscription(connection.tenant_id, sub.subscription_id)
            sub.display_name = info.display_name or sub.display_name
            sub.state = info.state
        await progress.finish(current, f"{len(subscriptions)} subscription(s) verified")

        sub_ids = list(subscriptions.keys())
        current = "permissions"
        await progress.start(current)
        groups = await azure.resource_graph.discover_resource_groups(connection.tenant_id, sub_ids)
        await progress.finish(current, "Resource Graph read access confirmed")

        current = "discover"
        await progress.start(current)
        discovered = await azure.resource_graph.discover_resources(connection.tenant_id, sub_ids)
        await progress.finish(current, f"{len(discovered)} resources discovered")

        current = "categorise"
        await progress.start(current)
        stats = await _upsert(db, connection, subscriptions, groups, discovered)
        run.stats = stats
        await progress.finish(
            current,
            f"{stats['created']} new, {stats['updated']} updated, {stats['removed']} removed",
        )

        current = "dashboards"
        await progress.start(current)
        dash_stats = await generate_dashboards(db, connection.organization_id, connection_id=connection.id)
        run.stats = {**stats, **dash_stats}
        await progress.finish(
            current, f"{dash_stats['dashboards_created']} created, {dash_stats['dashboards_updated']} updated"
        )

        current = "health"
        await progress.start(current)
        try:
            health = await evaluate_resources(db, azure, connection.organization_id, connection_id=connection.id)
            await progress.finish(current, f"{health['evaluated']} resources evaluated")
        except AppError as exc:
            # Health can be retried by the scheduler; don't fail the whole sync.
            await progress.finish(current, exc.message, status="failed")

        connection.status = "connected"
        connection.last_sync_at = now_utc()
        connection.last_error_code = connection.last_error_message = None
        run.status = "succeeded"
    except AppError as exc:
        SYNC_FAILURES.inc(exc.code)
        await db.rollback()
        await db.refresh(run)
        await db.refresh(connection)
        await SyncProgress(db, run).fail_remaining(current, exc.message)
        run.status, run.error_code, run.error_message = "failed", exc.code, exc.message
        connection.status = "error"
        connection.last_error_code, connection.last_error_message = exc.code, exc.message
        logger.warning("sync_failed", extra={"connection_id": str(connection.id), "error_code": exc.code})
    except Exception:
        SYNC_FAILURES.inc("INTERNAL_ERROR")
        logger.exception("sync_crashed", extra={"connection_id": str(run.connection_id)})
        await db.rollback()
        await db.refresh(run)
        await db.refresh(connection)
        message = "An unexpected error occurred during synchronisation."
        await SyncProgress(db, run).fail_remaining(current, message)
        run.status, run.error_code, run.error_message = "failed", "INTERNAL_ERROR", message
        connection.status = "error"
        connection.last_error_code, connection.last_error_message = "INTERNAL_ERROR", message
    finally:
        run.finished_at = now_utc()
        await db.commit()
        await get_cache().delete_prefix("amp:overview")


async def run_sync_job(sync_run_id: str) -> None:
    """Entry point for the worker / inline job runner."""
    JOB_RUNS.inc("sync")
    try:
        async with session_scope() as db:
            run = await db.get(SyncRun, uuid.UUID(sync_run_id))
            if run is None or run.status not in ("queued",):
                return
            await execute_sync(db, run, get_azure_services())
    except Exception:
        JOB_FAILURES.inc("sync")
        logger.exception("sync_job_failed", extra={"sync_run_id": sync_run_id})
        raise


async def active_run(db: AsyncSession, connection_id: uuid.UUID) -> SyncRun | None:
    run = await db.scalar(
        select(SyncRun)
        .where(SyncRun.connection_id == connection_id, SyncRun.status.in_(["queued", "running"]))
        .order_by(SyncRun.created_at.desc())
    )
    if run and (now_utc() - _aware(run.created_at)) > STALE_RUN_AFTER:
        run.status, run.error_code, run.error_message = "failed", "STALE", "The run did not complete in time."
        run.finished_at = now_utc()
        return None
    return run


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def mark_interrupted_runs(db: AsyncSession) -> int:
    """In-process (inline) jobs cannot survive a restart: close any run left queued or running."""
    runs = list(await db.scalars(select(SyncRun).where(SyncRun.status.in_(["queued", "running"]))))
    for run in runs:
        for step in run.steps:
            if step["status"] in ("pending", "running"):
                step["status"] = "skipped" if step["status"] == "pending" else "failed"
        flag_modified(run, "steps")
        run.status, run.error_code, run.finished_at = "failed", "INTERRUPTED", now_utc()
        run.error_message = "The API restarted while this run was in progress."
    return len(runs)


async def reassign_resources(db: AsyncSession, organization_id: uuid.UUID) -> int:
    """Re-applies tag and naming-convention assignment to every non-manual resource.

    Called when projects or environments change, so a new project picks up its resources at once
    instead of at the next synchronisation. Uses the stored tags (no Azure calls). Returns changes.
    """
    projects = list(
        await db.scalars(
            select(Project)
            .where(Project.organization_id == organization_id, Project.deleted_at.is_(None))
            .options(selectinload(Project.environments))
            # Projects created earlier in this request may be cached without their new environments.
            .execution_options(populate_existing=True)
        )
    )
    envs_by_project = {p.id: list(p.environments) for p in projects}
    connections = {
        c.id: c
        for c in await db.scalars(select(AzureConnection).where(AzureConnection.organization_id == organization_id))
    }
    group_tags = {
        g.id: g.tags or {}
        for g in await db.scalars(select(ResourceGroup).where(ResourceGroup.organization_id == organization_id))
    }
    changed = 0
    for row in await db.scalars(
        select(Resource).where(
            Resource.organization_id == organization_id,
            Resource.deleted_at.is_(None),
            Resource.assignment_source != "manual",
        )
    ):
        connection = connections.get(row.connection_id)
        merged_tags = (
            {**group_tags.get(row.resource_group_id, {}), **(row.tags or {})}
            if row.resource_group_id
            else row.tags or {}
        )
        result = assign(
            merged_tags,
            projects,
            envs_by_project,
            connection.default_project_id if connection else None,
            connection.default_environment_id if connection else None,
            resource_name=row.name,
            resource_group=row.resource_group,
        )
        if (row.project_id, row.environment_id, row.assignment_source) != result:
            row.project_id, row.environment_id, row.assignment_source = result
            changed += 1
    return changed
