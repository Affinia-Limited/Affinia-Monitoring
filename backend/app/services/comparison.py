"""Environment comparison: the same key metrics side by side for each environment of a project."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Resource
from app.schemas.misc import ComparisonOut, ComparisonRow
from app.services.azure.types import AzureServices, TimeRange
from app.services.metric_service import MetricService, reduce_values
from app.services.monitors.registry import get_monitor
from app.services.relations import tenant_for_resource


async def compare_environments(
    db: AsyncSession, azure: AzureServices, project: Project, time_range: TimeRange
) -> ComparisonOut:
    envs = list(project.environments)
    resources = list(
        await db.scalars(
            select(Resource).where(
                Resource.project_id == project.id,
                Resource.deleted_at.is_(None),
                Resource.environment_id.in_([e.id for e in envs]),
            )
        )
    )
    by_monitor: dict[str, list[Resource]] = defaultdict(list)
    for r in resources:
        if r.monitor_key:
            by_monitor[r.monitor_key].append(r)

    service = MetricService(db, azure)
    interval = time_range.auto_interval(24)
    tenants: dict[object, str] = {}
    rows: list[ComparisonRow] = []
    is_mock = False
    for monitor_key, items in sorted(by_monitor.items()):
        monitor = get_monitor(monitor_key)
        for comp in monitor.comparison:
            definition = monitor.metric(comp.metric)
            if definition is None:
                continue
            per_env: dict[str, list[float]] = defaultdict(list)
            counts: dict[str, int] = defaultdict(int)
            for resource in items:
                if resource.connection_id not in tenants:
                    tenants[resource.connection_id] = await tenant_for_resource(db, resource)
                [data] = await service.get_metrics(
                    resource, tenants[resource.connection_id], [comp.metric], time_range, interval
                )
                if data.unavailable_reason:
                    continue
                is_mock = is_mock or data.is_mock
                values = [p["value"] for s in data.series[:1] for p in s["points"] if p["value"] is not None]
                value = reduce_values(values, comp.rollup)
                if value is not None:
                    env_key = str(resource.environment_id)
                    per_env[env_key].append(value)
                    counts[env_key] += 1
            rows.append(
                ComparisonRow(
                    monitor_key=monitor.key,
                    monitor_name=monitor.display_name,
                    metric=comp.metric,
                    label=comp.label or definition.label,
                    unit=definition.unit,
                    rollup=comp.rollup,
                    # Sums add up across resources; averages/max are combined with the same rollup.
                    values={str(e.id): reduce_values(per_env.get(str(e.id), []), comp.rollup) for e in envs},
                    resource_counts={str(e.id): counts.get(str(e.id), 0) for e in envs},
                )
            )
    return ComparisonOut(
        project_id=project.id,
        environments=[{"id": str(e.id), "name": e.name, "kind": e.kind, "slug": e.slug} for e in envs],
        rows=rows,
        start=time_range.start,
        end=time_range.end,
        is_mock=is_mock,
    )
