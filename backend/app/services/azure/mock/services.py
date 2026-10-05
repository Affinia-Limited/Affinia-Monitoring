"""MOCK DATA - deterministic implementations of the Azure service interfaces.

Values are synthetic, generated from a hash of (resource, metric, timestamp) so
charts are stable between reloads. Every result is flagged ``is_mock=True`` and
the UI shows a "Demo data" badge. Used only with ``AZURE_PROVIDER=mock``.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.errors import AzureNotFoundError
from app.services.azure.mock.estate import MOCK_SUBSCRIPTIONS, MOCK_TENANT_ID, mock_estate
from app.services.azure.types import (
    DiscoveredResource,
    DiscoveredResourceGroup,
    LogColumn,
    LogQueryResult,
    MetricPoint,
    MetricRequest,
    MetricResult,
    MetricSeries,
    ResourceChange,
    ResourceHealthState,
    ServiceHealthEvent,
    SubscriptionInfo,
    TimeRange,
)


def _noise(*parts: object) -> float:
    """Deterministic pseudo-random float in [0, 1)."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _daily(ts: datetime) -> float:
    """0..1 business-hours curve peaking mid-afternoon UTC."""
    hour = ts.hour + ts.minute / 60
    return 0.5 + 0.5 * math.sin((hour - 9) / 24 * 2 * math.pi)


class MockResourceGraphService:
    async def list_subscriptions(self, tenant_id: str) -> list[SubscriptionInfo]:
        return list(MOCK_SUBSCRIPTIONS)

    async def get_subscription(self, tenant_id: str, subscription_id: str) -> SubscriptionInfo:
        for sub in MOCK_SUBSCRIPTIONS:
            if sub.subscription_id == subscription_id.lower():
                return sub
        if not re.fullmatch(r"[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}", subscription_id.lower()):
            raise AzureNotFoundError()
        return SubscriptionInfo(subscription_id.lower(), "Demo - Additional subscription", tenant_id, "Enabled")

    async def discover_resource_groups(
        self, tenant_id: str, subscription_ids: list[str]
    ) -> list[DiscoveredResourceGroup]:
        return mock_estate(subscription_ids)[0]

    async def discover_resources(self, tenant_id: str, subscription_ids: list[str]) -> list[DiscoveredResource]:
        return mock_estate(subscription_ids)[1]

    async def resource_health(self, tenant_id: str, subscription_ids: list[str]) -> list[ResourceHealthState]:
        states = []
        for r in mock_estate(subscription_ids)[1]:
            state, summary = "Available", "There aren't any known Azure platform problems affecting this resource."
            if r.name == "app-prism-prod-uks":
                state, summary = "Degraded", "Demo: the app is experiencing degraded performance."
            states.append(ResourceHealthState(r.azure_id, state, summary, None, None))
        return states

    async def service_health(self, tenant_id: str, subscription_ids: list[str]) -> list[ServiceHealthEvent]:
        if not subscription_ids:
            return []
        return [
            ServiceHealthEvent(
                event_id="DEMO-0001",
                title="Demo advisory: planned maintenance for App Service in UK South",
                event_type="PlannedMaintenance",
                status="Active",
                level="Informational",
                services=["App Service"],
                regions=["UK South"],
                last_update=datetime.now(UTC) - timedelta(hours=3),
                subscription_id=subscription_ids[0],
            )
        ]

    async def recent_changes(
        self, tenant_id: str, subscription_ids: list[str], limit: int = 50
    ) -> list[ResourceChange]:
        now = datetime.now(UTC)
        changes = []
        resources = [r for r in mock_estate(subscription_ids)[1] if r.resource_type == "microsoft.web/sites"]
        for i, r in enumerate(resources[:limit]):
            changes.append(
                ResourceChange(
                    azure_id=r.azure_id,
                    change_type="Update",
                    changed_at=now - timedelta(hours=2 + i * 5),
                    changed_by="demo-pipeline",
                    operation="Microsoft.Web/sites/write",
                )
            )
        return changes


# ---- metrics --------------------------------------------------------------------------

_DIMENSIONS: dict[str, list[tuple[str, float]]] = {
    "HttpStatusGroup": [("2xx", 0.93), ("3xx", 0.04), ("4xx", 0.028), ("5xx", 0.002)],
    "ClientCountry": [
        ("United Kingdom", 0.62),
        ("United States", 0.14),
        ("Germany", 0.09),
        ("India", 0.08),
        ("France", 0.07),
    ],
    "Action": [("Allow", 0.97), ("Log", 0.02), ("Block", 0.01)],
    "ResponseType": [("Success", 0.98), ("ClientOtherError", 0.015), ("ServerOtherError", 0.005)],
    "StatusCode": [("200", 0.95), ("401", 0.02), ("404", 0.02), ("429", 0.008), ("500", 0.002)],
    "phase": [("Running", 0.95), ("Pending", 0.04), ("Failed", 0.01)],
    "condition": [("Ready", 1.0), ("NotReady", 0.0)],
}


def _profile(name: str) -> tuple[str, float, float]:
    """(unit, baseline, spread) for a metric name. Counts are per minute."""
    n = name.lower()
    if "availability" in n or n in (
        "healthcheckstatus",
        "originhealthpercentage",
        "backendhealthpercentage",
        "vipavailability",
        "dipavailability",
    ):
        return ("Percent", 99.95, 0.05)
    if n == "vmavailabilitymetric":
        return ("Count", 1.0, 0.0)
    if "percent" in n or n in (
        "cpupercentage",
        "memorypercentage",
        "percentage cpu",
        "serverload",
        "saturationshoebox",
        "normalizedruconsumption",
        "percentprocessortime",
    ):
        if "4xx" in n:
            return ("Percent", 2.5, 1.5)
        if "5xx" in n:
            return ("Percent", 0.2, 0.2)
        if "storage" in n:
            return ("Percent", 38, 1)
        return ("Percent", 35, 25)
    if n in ("httpresponsetime",):
        return ("Seconds", 0.14, 0.08)
    if "latency" in n or "duration" in n or n in ("applicationgatewaytotaltime", "rundduration"):
        return ("MilliSeconds", 120, 80)
    if any(
        k in n
        for k in (
            "5xx",
            "failed",
            "error",
            "deadlock",
            "blocked",
            "throttled",
            "deadletter",
            "unhealthy",
            "ddos",
            "exceptions",
        )
    ):
        return ("Count", 0.15, 0.3)
    if any(
        k in n
        for k in (
            "bytes",
            "size",
            "ingress",
            "egress",
            "storage",
            "capacity",
            "usage",
            "memoryworkingset",
            "throughput",
        )
    ):
        return ("Bytes", 6e7, 3e7)
    if any(k in n for k in ("connections", "clients", "sessions", "queue", "hosts", "inflight", "active")):
        return ("Count", 12, 8)
    return ("Count", 180, 120)


class MockMetricsService:
    async def query(
        self,
        tenant_id: str,
        resource_azure_id: str,
        metrics: list[MetricRequest],
        time_range: TimeRange,
        interval: timedelta,
    ) -> list[MetricResult]:
        results = []
        minutes = interval.total_seconds() / 60
        start = datetime.fromtimestamp(
            (time_range.start.timestamp() // interval.total_seconds()) * interval.total_seconds(), UTC
        )
        now = datetime.now(UTC)
        stressed = "prism-prod" in resource_azure_id
        for metric in metrics:
            unit, base, spread = _profile(metric.name)
            is_count = unit == "Count" and metric.aggregation in ("Total", "Count")
            dims = _DIMENSIONS.get(metric.split_by or "", [("", 1.0)])
            series = []
            for dim_value, share in dims:
                points = []
                ts = start
                while ts <= time_range.end:
                    shape = _daily(ts)
                    jitter = _noise(resource_azure_id, metric.name, dim_value, ts.isoformat())
                    if unit == "Percent" and base > 99:
                        value = min(100.0, base + (jitter - 0.3) * spread)
                    elif unit == "Percent":
                        value = base + spread * (0.6 * shape + 0.4 * jitter)
                        if stressed and ("cpu" in metric.name.lower() or "memory" in metric.name.lower()):
                            value = 80 + 8 * jitter
                        value = max(0.0, min(100.0, value))
                    else:
                        value = base + spread * (shape + jitter - 1)
                        value = max(0.0, value)
                        if is_count:
                            value *= minutes
                        if (
                            "crm-prod" in resource_azure_id
                            and "5xx" in metric.name.lower()
                            and now - ts < timedelta(minutes=45)
                        ):
                            value += 3 * minutes  # demo: a recent 5xx increase
                    value *= share if metric.split_by else 1
                    if is_count:
                        value = round(value)
                    points.append(MetricPoint(timestamp=ts, value=round(value, 4) if ts <= now else None))
                    ts += interval
                series.append(
                    MetricSeries(dimensions={metric.split_by: dim_value} if metric.split_by else {}, points=points)
                )
            results.append(
                MetricResult(
                    name=metric.name,
                    unit=unit,
                    aggregation=metric.aggregation,
                    interval=interval,
                    series=series,
                    is_mock=True,
                )
            )
        return results


# ---- logs -----------------------------------------------------------------------------

_TIME_COLUMNS = {"timegenerated", "timestamp"}
_SAMPLE: dict[str, list[Any]] = {
    "status": [200, 200, 200, 200, 201, 204, 304, 401, 404, 500],
    "method": ["GET", "GET", "GET", "POST", "PUT", "DELETE"],
    "path": ["/api/customers", "/api/orders", "/health", "/api/search", "/login", "/api/reports/export"],
    "level": ["Informational", "Informational", "Informational", "Warning", "Error"],
    "message": [
        "Demo: request completed",
        "Demo: cache refreshed",
        "Demo: background job finished",
        "Demo: retrying transient SQL failure",
        "Demo: upstream timeout calling payments API",
    ],
    "type": ["System.TimeoutException", "Microsoft.Data.SqlClient.SqlException", "System.NullReferenceException"],
    "target": ["sql-demo.database.windows.net", "api.payments.demo", "kv-demo.vault.azure.net", "storage.demo"],
    "role": ["web-frontend", "orders-api", "worker"],
    "country": ["United Kingdom", "United States", "Germany", "India", "France"],
}


def _column_value(column: str, i: int, ts: datetime, seed: str) -> Any:
    c = column.lower()
    r = _noise(seed, column, i)
    if c in _TIME_COLUMNS:
        return ts.isoformat()
    if "status" in c or c in ("resultcode", "scstatus"):
        return _SAMPLE["status"][int(r * len(_SAMPLE["status"]))]
    if "method" in c:
        return _SAMPLE["method"][int(r * len(_SAMPLE["method"]))]
    if c in ("csuristem", "requesturi_s", "operation_name", "name", "query_hash_s", "rulename_s"):
        return _SAMPLE["path"][int(r * len(_SAMPLE["path"]))]
    if c in ("level", "severity", "severitylevel"):
        return _SAMPLE["level"][int(r * len(_SAMPLE["level"]))]
    if c in ("resultdescription", "message", "outermessage"):
        return _SAMPLE["message"][int(r * len(_SAMPLE["message"]))]
    if c == "type":
        return _SAMPLE["type"][int(r * len(_SAMPLE["type"]))]
    if c in ("target",):
        return _SAMPLE["target"][int(r * len(_SAMPLE["target"]))]
    if c in ("cloud_rolename", "source"):
        return _SAMPLE["role"][int(r * len(_SAMPLE["role"]))]
    if "country" in c:
        return _SAMPLE["country"][int(r * len(_SAMPLE["country"]))]
    if c in ("success",):
        return r > 0.05
    if any(k in c for k in ("ms", "duration", "timetaken", "time_d")):
        return round(40 + r * 400, 1)
    if any(
        k in c
        for k in ("count", "calls", "errors", "hits", "failures", "failed", "requests", "runs", "passed", "executions")
    ):
        return int(r * 500)
    if c in ("host", "cshost"):
        return "demo-host-1"
    if c.endswith("_s"):
        return "demo"
    return f"demo-{int(r * 1000)}"


def _summarize_parts(kql: str) -> tuple[list[str], list[str]] | None:
    match = re.search(r"\|\s*summarize\s+(.+?)(?:\s+by\s+(.+?))?\s*(?:\||$)", kql, re.S | re.I)
    if not match:
        return None
    # Aliases may be plain (Requests = count()) or bracketed (['5xx'] = countif(...)).
    aggs = [a or b for a, b in re.findall(r"(?:\[\s*'([^']+)'\s*\]|(\w+))\s*=\s*\w+\(", match.group(1))] or ["count_"]
    by_clause = match.group(2) or ""
    by_cols = []
    for part in re.split(r",(?![^(]*\))", by_clause):
        part = part.strip()
        if not part:
            continue
        alias = re.match(r"(\w+)\s*=", part)
        bin_match = re.match(r"bin\(\s*(\w+)", part)
        by_cols.append(alias.group(1) if alias else bin_match.group(1) if bin_match else part.split()[0])
    return aggs, by_cols


class MockLogsService:
    async def query_resource(
        self, tenant_id: str, resource_azure_id: str, kql: str, time_range: TimeRange, max_rows: int
    ) -> LogQueryResult:
        seed = resource_azure_id + kql
        summarize = _summarize_parts(kql)
        rows: list[list[Any]] = []
        if summarize:
            aggs, by_cols = summarize
            columns = [LogColumn(c, "datetime" if c.lower() in _TIME_COLUMNS else "string") for c in by_cols]
            columns += [LogColumn(a, "long") for a in aggs]
            is_timeseries = any(c.lower() in _TIME_COLUMNS for c in by_cols)
            if is_timeseries:
                step = time_range.auto_interval(60)
                ts = time_range.start
                i = 0
                while ts <= time_range.end:
                    row = [
                        ts.isoformat() if c.name.lower() in _TIME_COLUMNS else _column_value(c.name, i, ts, seed)
                        for c in columns[: len(by_cols)]
                    ]
                    row += [
                        int(_noise(seed, a, i) * (20 if "fail" in a.lower() or "error" in a.lower() else 300))
                        for a in aggs
                    ]
                    rows.append(row)
                    ts += step
                    i += 1
            else:
                for i in range(8):
                    row = [_column_value(c, i, time_range.end, seed) for c in by_cols]
                    row += [int(_noise(seed, a, i) * 400) for a in aggs]
                    rows.append(row)
                rows.sort(key=lambda r: r[-1], reverse=True)
        else:
            project = re.search(r"\|\s*project\s+([^|]+)", kql, re.I)
            names = (
                [p.strip().split("=")[0].strip() for p in project.group(1).split(",")]
                if project
                else ["TimeGenerated", "Level", "Message"]
            )
            columns = [LogColumn(n, "datetime" if n.lower() in _TIME_COLUMNS else "string") for n in names]
            count = min(max_rows, 60)
            span = time_range.duration / max(count, 1)
            for i in range(count):
                ts = time_range.end - span * i
                rows.append([_column_value(n, i, ts, seed) for n in names])
        truncated = len(rows) > max_rows
        return LogQueryResult(columns=columns, rows=rows[:max_rows], truncated=truncated, is_mock=True)


__all__ = ["MOCK_TENANT_ID", "MockLogsService", "MockMetricsService", "MockResourceGraphService"]
