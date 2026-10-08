"""MetricService: the single entry point for metric data.

Callers ask for metric *keys* defined by the resource's monitor plugin; this
service resolves the Azure metric name, namespace, aggregation, dimension split
and target resource (for metrics that live on a related resource such as the
App Service Plan), applies caching, and returns a provider-neutral structure.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_key, get_cache
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.models import Resource
from app.services.azure.types import AzureServices, MetricRequest, MetricResult, TimeRange
from app.services.monitors.base import MetricDef, Rollup
from app.services.monitors.registry import get_monitor
from app.services.relations import related_resource

logger = logging.getLogger(__name__)


@dataclass
class MetricData:
    key: str
    label: str
    unit: str
    aggregation: str
    interval_seconds: int
    series: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, float | None] = field(default_factory=dict)
    source_resource_id: str | None = None
    #: Machine-readable reason when no data could be returned (e.g. ``RELATED_RESOURCE_NOT_FOUND``).
    unavailable_reason: str | None = None
    unavailable_message: str | None = None
    is_mock: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def reduce_values(values: list[float], reducer: Rollup) -> float | None:
    if not values:
        return None
    if reducer == "sum":
        return float(sum(values))
    if reducer == "max":
        return float(max(values))
    if reducer == "min":
        return float(min(values))
    return float(sum(values) / len(values))


def _summarise(series: list[dict[str, Any]]) -> dict[str, float | None]:
    values = [p["value"] for s in series for p in s["points"] if p["value"] is not None]
    latest = None
    for s in series[:1]:
        for p in reversed(s["points"]):
            if p["value"] is not None:
                latest = p["value"]
                break
    return {
        "avg": reduce_values(values, "avg"),
        "min": reduce_values(values, "min"),
        "max": reduce_values(values, "max"),
        "sum": reduce_values(values, "sum"),
        "latest": latest,
    }


def _series_name(definition: MetricDef, dimensions: dict[str, str]) -> str:
    if not dimensions:
        return definition.label
    return ", ".join(v for v in dimensions.values()) or definition.label


def _normalise(definition: MetricDef, result: MetricResult) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for s in result.series:
        points = [
            {"timestamp": p.timestamp.isoformat(), "value": None if p.value is None else p.value * definition.scale}
            for p in s.points
        ]
        series.append({"name": _series_name(definition, s.dimensions), "dimensions": s.dimensions, "points": points})
    # Stable ordering for split series: largest total first.
    if definition.split_by:
        series.sort(key=lambda item: -sum(p["value"] or 0 for p in item["points"]))
    return series


class MetricService:
    def __init__(self, db: AsyncSession, azure: AzureServices):
        self._db = db
        self._azure = azure
        self._settings = get_settings()

    async def _target(self, resource: Resource, definition: MetricDef) -> Resource | None:
        if definition.target == "self":
            return resource
        relation = definition.target.split(":", 1)[1]
        return await related_resource(self._db, resource, relation)

    async def _fetch(
        self, tenant_id: str, target: Resource, definition: MetricDef, time_range: TimeRange, interval: timedelta
    ) -> MetricResult | None:
        request = MetricRequest(definition.name, definition.aggregation, definition.namespace, definition.split_by)
        key = cache_key(
            "metrics",
            tenant_id,
            target.azure_id,
            request.name,
            request.aggregation,
            request.namespace,
            request.split_by,
            time_range.start.isoformat(),
            time_range.end.isoformat(),
            interval.total_seconds(),
        )
        cache = get_cache()
        cached = await cache.get(key)
        if cached is not None:
            return _result_from_cache(cached)
        results = await self._azure.metrics.query(tenant_id, target.azure_id, [request], time_range, interval)
        result = results[0] if results else None
        if result is not None:
            await cache.set(key, _result_to_cache(result), self._settings.cache_ttl_metrics)
        return result

    async def _prepare(
        self, resource: Resource, key: str, interval: timedelta
    ) -> tuple[MetricData, MetricDef, Resource | None, timedelta]:
        """Resolve a metric key to its definition and target resource (database work only)."""
        monitor = get_monitor(resource.monitor_key)
        definition = monitor.metric(key)
        if definition is None:
            raise NotFoundError(f"Metric '{key}' is not defined for {monitor.display_name}.", code="METRIC_NOT_FOUND")
        metric_interval = interval
        if definition.min_interval_minutes:
            metric_interval = max(interval, timedelta(minutes=definition.min_interval_minutes))
        data = MetricData(
            key=key,
            label=definition.label,
            unit=definition.unit,
            aggregation=definition.aggregation,
            interval_seconds=int(metric_interval.total_seconds()),
        )
        target = await self._target(resource, definition)
        if target is None:
            data.unavailable_reason = "RELATED_RESOURCE_NOT_FOUND"
            data.unavailable_message = "The related resource for this metric has not been discovered."
        else:
            data.source_resource_id = str(target.id)
        return data, definition, target, metric_interval

    async def _complete(
        self,
        data: MetricData,
        definition: MetricDef,
        tenant_id: str,
        target: Resource,
        time_range: TimeRange,
        interval: timedelta,
    ) -> None:
        """Fetch a prepared metric from Azure (or the cache); no database access."""
        try:
            result = await self._fetch(tenant_id, target, definition, time_range, interval)
        except AppError as exc:
            # One unavailable metric must not break a whole dashboard.
            data.unavailable_reason = exc.code
            data.unavailable_message = exc.message
            return
        if result is None or not result.series:
            data.unavailable_reason = "NO_DATA"
            data.unavailable_message = "Azure returned no data for this metric."
        else:
            data.series = _normalise(definition, result)
            data.summary = _summarise(data.series)
            data.is_mock = result.is_mock

    async def get_metrics(
        self,
        resource: Resource,
        tenant_id: str,
        keys: list[str],
        time_range: TimeRange,
        interval: timedelta | None = None,
    ) -> list[MetricData]:
        interval = interval or time_range.auto_interval()
        output: list[MetricData] = []
        for key in keys:
            data, definition, target, metric_interval = await self._prepare(resource, key, interval)
            if target is not None:
                await self._complete(data, definition, tenant_id, target, time_range, metric_interval)
            output.append(data)
        return output

    async def get_metrics_many(
        self,
        requests: Sequence[tuple[Resource, str, list[str]]],
        time_range: TimeRange,
        interval: timedelta,
        concurrency: int = 8,
    ) -> list[list[MetricData]]:
        """``get_metrics`` for many ``(resource, tenant_id, keys)`` at once.

        Related-resource lookups run one at a time on the shared session; the Azure
        calls then run concurrently, at most ``concurrency`` in flight.
        """
        prepared: list[list[tuple[str, MetricData, MetricDef, Resource | None, timedelta]]] = []
        for resource, tenant_id, keys in requests:
            prepared.append([(tenant_id, *await self._prepare(resource, key, interval)) for key in keys])
        gate = asyncio.Semaphore(concurrency)

        async def run(
            tenant_id: str, data: MetricData, definition: MetricDef, target: Resource | None, step: timedelta
        ) -> None:
            if target is None:
                return
            async with gate:
                await self._complete(data, definition, tenant_id, target, time_range, step)

        await asyncio.gather(*(run(*item) for group in prepared for item in group))
        return [[item[1] for item in group] for group in prepared]

    async def window_value(
        self, resource: Resource, tenant_id: str, key: str, window_minutes: int, reducer: Rollup
    ) -> tuple[float | None, str | None]:
        """Single value for the last ``window_minutes`` (used by health and alert evaluation)."""
        time_range = TimeRange.from_params("custom", *_window(window_minutes))
        interval = timedelta(minutes=5) if window_minutes >= 15 else timedelta(minutes=1)
        [data] = await self.get_metrics(resource, tenant_id, [key], time_range, interval)
        if data.unavailable_reason:
            return None, data.unavailable_reason
        values = [p["value"] for s in data.series[:1] for p in s["points"] if p["value"] is not None]
        return reduce_values(values, reducer), None


def _window(minutes: int) -> tuple[Any, Any]:
    from datetime import UTC, datetime

    end = datetime.now(UTC).replace(second=0, microsecond=0)
    return end - timedelta(minutes=minutes), end


def _result_to_cache(result: MetricResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "unit": result.unit,
        "aggregation": result.aggregation,
        "interval": result.interval.total_seconds(),
        "is_mock": result.is_mock,
        "series": [
            {"dimensions": s.dimensions, "points": [[p.timestamp.isoformat(), p.value] for p in s.points]}
            for s in result.series
        ],
    }


def _result_from_cache(data: dict[str, Any]) -> MetricResult:
    from datetime import datetime

    from app.services.azure.types import MetricPoint, MetricSeries

    return MetricResult(
        name=data["name"],
        unit=data["unit"],
        aggregation=data["aggregation"],
        interval=timedelta(seconds=data["interval"]),
        is_mock=data.get("is_mock", False),
        series=[
            MetricSeries(
                dimensions=s["dimensions"],
                points=[MetricPoint(datetime.fromisoformat(ts), v) for ts, v in s["points"]],
            )
            for s in data["series"]
        ],
    )
