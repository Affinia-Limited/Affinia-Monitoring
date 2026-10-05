"""Azure Monitor Metrics (real implementation)."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from azure.monitor.query.aio import MetricsQueryClient

from app.services.azure.credentials import CredentialProvider
from app.services.azure.errors import azure_call
from app.services.azure.types import MetricPoint, MetricRequest, MetricResult, MetricSeries, TimeRange

_AGG_ATTR = {
    "Average": "average",
    "Total": "total",
    "Maximum": "maximum",
    "Minimum": "minimum",
    "Count": "count",
}


class AzureMetricsService:
    def __init__(self, credentials: CredentialProvider):
        self._credentials = credentials

    async def query(
        self,
        tenant_id: str,
        resource_azure_id: str,
        metrics: list[MetricRequest],
        time_range: TimeRange,
        interval: timedelta,
    ) -> list[MetricResult]:
        # Azure requires one call per (namespace, aggregation, split dimension) combination.
        groups: dict[tuple[str | None, str, str | None], list[MetricRequest]] = defaultdict(list)
        for metric in metrics:
            groups[(metric.namespace, metric.aggregation, metric.split_by)].append(metric)

        results: list[MetricResult] = []
        credential = self._credentials.for_tenant(tenant_id)
        async with MetricsQueryClient(credential) as client:
            for (namespace, aggregation, split_by), group in groups.items():
                filter_expr = f"{split_by} eq '*'" if split_by else None
                async with azure_call("metrics.query"):
                    response = await client.query_resource(
                        resource_azure_id,
                        metric_names=[m.name for m in group],
                        timespan=(time_range.start, time_range.end),
                        granularity=interval,
                        aggregations=[aggregation],
                        metric_namespace=namespace,
                        filter=filter_expr,
                        max_results=20 if split_by else None,
                    )
                attr = _AGG_ATTR.get(aggregation, "average")
                for item in response.metrics:
                    series = [
                        MetricSeries(
                            dimensions={str(k): str(v) for k, v in (ts.metadata_values or {}).items()},
                            points=[MetricPoint(timestamp=p.timestamp, value=getattr(p, attr)) for p in ts.data],
                        )
                        for ts in item.timeseries
                    ]
                    results.append(
                        MetricResult(
                            name=item.name,
                            unit=str(item.unit or ""),
                            aggregation=aggregation,
                            interval=interval,
                            series=series,
                        )
                    )
        return results
