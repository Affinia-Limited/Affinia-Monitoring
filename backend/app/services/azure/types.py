"""Provider-neutral data structures and interfaces for Azure access.

Route handlers and domain services depend only on these Protocols. Two
implementations exist: ``app.services.azure.real`` (Azure SDK) and
``app.services.azure.mock`` (deterministic demo data for development/tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

TimeRangePreset = Literal["30m", "1h", "6h", "24h", "7d", "30d"]

_PRESETS: dict[str, timedelta] = {
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# Azure Monitor supported granularities.
_GRANULARITIES = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=12),
    timedelta(days=1),
]

MAX_CUSTOM_RANGE = timedelta(days=93)


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime
    preset: str | None = None

    @classmethod
    def from_params(cls, preset: str | None, start: datetime | None = None, end: datetime | None = None) -> TimeRange:
        from app.core.errors import ValidationFailedError

        now = datetime.now(UTC)
        if preset and preset != "custom":
            if preset not in _PRESETS:
                raise ValidationFailedError(f"Unsupported time range '{preset}'.")
            # Round the end to the minute so cache keys are stable within a minute.
            end_ts = now.replace(second=0, microsecond=0)
            return cls(start=end_ts - _PRESETS[preset], end=end_ts, preset=preset)
        if not (start and end):
            raise ValidationFailedError("A custom time range requires both start and end.")
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        if end <= start:
            raise ValidationFailedError("The end of the time range must be after the start.")
        if end - start > MAX_CUSTOM_RANGE:
            raise ValidationFailedError("Custom time ranges are limited to 93 days.")
        return cls(start=start, end=min(end, now), preset="custom")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def auto_interval(self, target_points: int = 90) -> timedelta:
        """Smallest Azure-supported granularity that yields at most ``target_points`` points."""
        ideal = self.duration / target_points
        for granularity in _GRANULARITIES:
            if granularity >= ideal:
                return granularity
        return _GRANULARITIES[-1]


@dataclass(frozen=True)
class SubscriptionInfo:
    subscription_id: str
    display_name: str
    tenant_id: str
    state: str


@dataclass(frozen=True)
class DiscoveredResourceGroup:
    azure_id: str
    name: str
    subscription_id: str
    location: str | None
    tags: dict[str, str]


@dataclass(frozen=True)
class DiscoveredResource:
    azure_id: str
    name: str
    resource_type: str
    kind: str | None
    sku: str | None
    location: str | None
    subscription_id: str
    resource_group: str
    tags: dict[str, str]
    properties: dict[str, Any]


@dataclass(frozen=True)
class ResourceHealthState:
    azure_id: str
    availability_state: str
    summary: str | None
    reason_type: str | None
    occurred_at: datetime | None


@dataclass(frozen=True)
class ServiceHealthEvent:
    event_id: str
    title: str
    event_type: str
    status: str
    level: str | None
    services: list[str]
    regions: list[str]
    last_update: datetime | None
    subscription_id: str


@dataclass(frozen=True)
class ResourceChange:
    azure_id: str
    change_type: str
    changed_at: datetime | None
    changed_by: str | None
    operation: str | None


@dataclass(frozen=True)
class MetricRequest:
    name: str
    aggregation: str
    namespace: str | None = None
    split_by: str | None = None


@dataclass
class MetricPoint:
    timestamp: datetime
    value: float | None


@dataclass
class MetricSeries:
    #: Dimension values for split series, e.g. {"HttpStatusGroup": "5xx"}; empty when unsplit.
    dimensions: dict[str, str]
    points: list[MetricPoint]


@dataclass
class MetricResult:
    name: str
    unit: str
    aggregation: str
    interval: timedelta
    series: list[MetricSeries]
    is_mock: bool = False


@dataclass
class LogColumn:
    name: str
    type: str


@dataclass
class LogQueryResult:
    columns: list[LogColumn]
    rows: list[list[Any]]
    truncated: bool = False
    partial_error: str | None = None
    is_mock: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class ResourceGraphService(Protocol):
    async def list_subscriptions(self, tenant_id: str) -> list[SubscriptionInfo]: ...

    async def get_subscription(self, tenant_id: str, subscription_id: str) -> SubscriptionInfo: ...

    async def discover_resource_groups(
        self, tenant_id: str, subscription_ids: list[str]
    ) -> list[DiscoveredResourceGroup]: ...

    async def discover_resources(self, tenant_id: str, subscription_ids: list[str]) -> list[DiscoveredResource]: ...

    async def resource_health(self, tenant_id: str, subscription_ids: list[str]) -> list[ResourceHealthState]: ...

    async def service_health(self, tenant_id: str, subscription_ids: list[str]) -> list[ServiceHealthEvent]: ...

    async def recent_changes(
        self, tenant_id: str, subscription_ids: list[str], limit: int = 50
    ) -> list[ResourceChange]: ...


class MetricsService(Protocol):
    async def query(
        self,
        tenant_id: str,
        resource_azure_id: str,
        metrics: list[MetricRequest],
        time_range: TimeRange,
        interval: timedelta,
    ) -> list[MetricResult]: ...


class LogsService(Protocol):
    async def query_resource(
        self, tenant_id: str, resource_azure_id: str, kql: str, time_range: TimeRange, max_rows: int
    ) -> LogQueryResult: ...


@dataclass
class AzureServices:
    resource_graph: ResourceGraphService
    metrics: MetricsService
    logs: LogsService
    is_mock: bool = False
