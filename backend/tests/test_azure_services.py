"""Real Azure service implementations, exercised with the Azure SDK clients mocked out.

These cover the production code paths (pagination, error mapping, normalisation)
without needing a subscription.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.monitor.query import LogsQueryResult, LogsQueryStatus, LogsTable

from app.core.config import get_settings
from app.core.errors import (
    AzureAuthenticationError,
    AzurePermissionDeniedError,
    AzureQueryError,
    AzureThrottledError,
)
from app.core.security import JwksCache
from app.services.azure import log_analytics, monitor, resource_graph
from app.services.azure.credentials import TenantScopedCredential
from app.services.azure.errors import azure_call
from app.services.azure.types import MetricRequest, TimeRange


class _Ctx:
    """Async context manager wrapper matching the SDK client shape."""

    def __init__(self, *args: Any, **kwargs: Any):
        pass

    async def __aenter__(self) -> _Ctx:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeCredentials:
    def for_tenant(self, tenant_id: str) -> str:
        return f"credential-for-{tenant_id}"


def _http_error(status: int, message: str = "boom") -> HttpResponseError:
    response = SimpleNamespace(status_code=status, reason="x", headers={}, text=lambda: message)
    error = HttpResponseError(message=message, response=response)  # type: ignore[arg-type]
    error.status_code = status
    return error


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_http_error(403), AzurePermissionDeniedError),
        (_http_error(401), AzurePermissionDeniedError),
        (_http_error(429), AzureThrottledError),
        (_http_error(400, "Syntax error: bad token at line 1"), AzureQueryError),
        (ClientAuthenticationError("no identity"), AzureAuthenticationError),
    ],
)
async def test_azure_errors_are_mapped(exc: Exception, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        async with azure_call("test"):
            raise exc


async def test_query_error_message_is_safe_and_short() -> None:
    with pytest.raises(AzureQueryError) as info:
        async with azure_call("test"):
            raise _http_error(400, "Syntax error near 'Bearer eyJabcdefghijk.eyJabcdefghijk.sig'\nstack...")
    assert "eyJ" not in info.value.message
    assert "\n" not in info.value.message


def test_row_to_resource_allow_lists_properties() -> None:
    row = {
        "id": "/SUBSCRIPTIONS/abc/resourceGroups/RG/providers/Microsoft.Web/sites/App1",
        "name": "App1",
        "type": "Microsoft.Web/sites",
        "kind": "app",
        "location": "uksouth",
        "resourceGroup": "rg",
        "subscriptionId": "abc",
        "tags": {"project": "CRM", "hidden-link: /app-insights-resource-id": "/x"},
        "skuName": "",
        "state": "Running",
        "serverFarmId": "/subscriptions/abc/resourcegroups/rg/providers/microsoft.web/serverfarms/plan",
        "connectionString": "Server=secret",  # not in the allow-list
    }
    resource = resource_graph.row_to_resource(row)
    assert resource.azure_id == row["id"].lower()
    assert resource.resource_type == "microsoft.web/sites"
    assert resource.tags == {"project": "CRM"}
    assert resource.sku is None
    assert "connectionString" not in resource.properties
    assert resource.properties["state"] == "Running"


async def test_resource_graph_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    class FakeGraph(_Ctx):
        async def resources(self, request: Any) -> Any:
            calls.append(request)
            if request.options.skip_token is None:
                return SimpleNamespace(
                    data=[{"id": "/a", "name": "a", "type": "t", "subscriptionId": "s"}], skip_token="next"
                )
            return SimpleNamespace(
                data=[{"id": "/b", "name": "b", "type": "t", "subscriptionId": "s"}], skip_token=None
            )

    monkeypatch.setattr(resource_graph, "ResourceGraphClient", FakeGraph)
    service = resource_graph.AzureResourceGraphService(FakeCredentials())  # type: ignore[arg-type]
    resources = await service.discover_resources("tenant", ["s"])
    assert [r.name for r in resources] == ["a", "b"]
    assert len(calls) == 2
    assert calls[0].subscriptions == ["s"]
    assert "resources" in calls[0].query


async def test_resource_graph_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Denied(_Ctx):
        async def resources(self, request: Any) -> Any:
            raise _http_error(403)

    monkeypatch.setattr(resource_graph, "ResourceGraphClient", Denied)
    service = resource_graph.AzureResourceGraphService(FakeCredentials())  # type: ignore[arg-type]
    with pytest.raises(AzurePermissionDeniedError):
        await service.discover_resources("tenant", ["s"])


async def test_metrics_groups_calls_and_splits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    class FakeMetrics(_Ctx):
        async def query_resource(self, resource_uri: str, metric_names: list[str], **kwargs: Any) -> Any:
            calls.append({"names": metric_names, **kwargs})
            metrics = []
            for name in metric_names:
                points = [
                    SimpleNamespace(timestamp=now, average=1.5, total=10.0, maximum=None, minimum=None, count=None)
                ]
                series = [
                    SimpleNamespace(
                        metadata_values={"httpstatusgroup": "5xx"} if kwargs.get("filter") else {}, data=points
                    )
                ]
                metrics.append(SimpleNamespace(name=name, unit="Count", timeseries=series))
            return SimpleNamespace(metrics=metrics)

    monkeypatch.setattr(monitor, "MetricsQueryClient", FakeMetrics)
    service = monitor.AzureMetricsService(FakeCredentials())  # type: ignore[arg-type]
    results = await service.query(
        "tenant",
        "/r",
        [
            MetricRequest("Requests", "Total"),
            MetricRequest("Http5xx", "Total"),
            MetricRequest("HttpResponseTime", "Average"),
            MetricRequest("RequestCount", "Total", split_by="HttpStatusGroup"),
        ],
        TimeRange.from_params("1h"),
        timedelta(minutes=1),
    )
    assert len(calls) == 3  # (Total), (Average), (Total + split)
    assert calls[0]["names"] == ["Requests", "Http5xx"]
    assert any(c.get("filter") == "HttpStatusGroup eq '*'" for c in calls)
    by_name = {r.name: r for r in results}
    assert by_name["Requests"].series[0].points[0].value == 10.0
    assert by_name["HttpResponseTime"].series[0].points[0].value == 1.5
    assert by_name["RequestCount"].series[0].dimensions == {"httpstatusgroup": "5xx"}


async def test_logs_are_resource_centric_and_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class FakeLogs(_Ctx):
        async def query_resource(self, resource_id: str, query: str, **kwargs: Any) -> Any:
            seen.update(resource_id=resource_id, query=query, **kwargs)
            table = LogsTable(
                name="t",
                columns=["TimeGenerated", "n"],
                columns_types=["datetime", "long"],
                rows=[[datetime(2026, 1, 1, tzinfo=UTC), i] for i in range(10)],
            )
            return LogsQueryResult(tables=[table], status=LogsQueryStatus.SUCCESS)

    monkeypatch.setattr(log_analytics, "LogsQueryClient", FakeLogs)
    service = log_analytics.AzureLogsService(FakeCredentials())  # type: ignore[arg-type]
    result = await service.query_resource(
        "tenant", "/subscriptions/x/resource", "T | take 10", TimeRange.from_params("1h"), max_rows=5
    )
    assert seen["resource_id"] == "/subscriptions/x/resource"
    assert seen["server_timeout"] == 60
    assert [c.name for c in result.columns] == ["TimeGenerated", "n"]
    assert len(result.rows) == 5 and result.truncated is True
    assert result.rows[0][0] == "2026-01-01T00:00:00+00:00"


async def test_tenant_scoped_credential_passes_tenant() -> None:
    captured: dict[str, Any] = {}

    class Inner:
        async def get_token(self, *scopes: str, **kwargs: Any) -> str:
            captured.update(scopes=scopes, **kwargs)
            return "token"

    await TenantScopedCredential(Inner(), "tenant-b").get_token("https://management.azure.com/.default")  # type: ignore[arg-type]
    assert captured["tenant_id"] == "tenant-b"
    captured.clear()
    await TenantScopedCredential(Inner(), None).get_token("scope")  # type: ignore[arg-type]
    assert "tenant_id" not in captured


async def test_jwks_cache_refreshes_on_key_rotation() -> None:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    keys = []
    fetches = 0

    def jwk(kid: str) -> dict[str, Any]:
        key = RSAAlgorithm.to_jwk(
            rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key(), as_dict=True
        )
        return {**key, "kid": kid}

    keys.append(jwk("k1"))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetches
        fetches += 1
        return httpx.Response(200, json={"keys": keys})

    cache = JwksCache(get_settings().entra_authority_host, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await cache.get_key("t", "k1")
    await cache.get_key("t", "k1")
    assert fetches == 1
    keys.append(jwk("k2"))
    await cache.get_key("t", "k2")
    assert fetches == 2


async def test_service_health_flattens_impact(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGraph(_Ctx):
        async def resources(self, request: Any) -> Any:
            assert "project evtId = name" in request.query
            row = {
                "evtId": "ABC-123",
                "evtTitle": "Planned maintenance",
                "evtType": "PlannedMaintenance",
                "evtStatus": "Active",
                "evtLevel": "Informational",
                "evtUpdated": "2026-10-01T04:00:00Z",
                "subscriptionId": "s",
                "evtImpact": [
                    {"ImpactedService": "App Service", "ImpactedRegions": [{"ImpactedRegion": "UK South"}]},
                    {
                        "ImpactedService": "SQL Database",
                        "ImpactedRegions": [{"ImpactedRegion": "UK South"}, {"ImpactedRegion": "UK West"}],
                    },
                ],
            }
            return SimpleNamespace(data=[row], skip_token=None)

    monkeypatch.setattr(resource_graph, "ResourceGraphClient", FakeGraph)
    service = resource_graph.AzureResourceGraphService(FakeCredentials())  # type: ignore[arg-type]
    [event] = await service.service_health("tenant", ["s"])
    assert event.title == "Planned maintenance" and event.status == "Active"
    assert event.services == ["App Service", "SQL Database"]
    assert event.regions == ["UK South", "UK West"]
    assert event.last_update is not None


async def test_unsupported_metric_maps_to_specific_code() -> None:
    message = "Failed to find metric configuration for provider: Microsoft.Web, metric: AppConnections"
    with pytest.raises(AzureQueryError) as info:
        async with azure_call("metrics.query"):
            raise _http_error(400, message)
    assert info.value.code == "METRIC_NOT_SUPPORTED"


async def test_missing_log_table_maps_to_setup_hint() -> None:
    message = "'summarize' operator: Failed to resolve table or column expression named 'AppServiceHTTPLogs'"
    with pytest.raises(AzureQueryError) as info:
        async with azure_call("logs.query_resource"):
            raise _http_error(400, message)
    assert info.value.code == "LOG_TABLE_NOT_FOUND"
    assert "Diagnostic settings" in info.value.message


async def test_caching_credential_reuses_and_deduplicates_tokens() -> None:
    import asyncio
    import time as _time

    from azure.core.credentials import AccessToken

    from app.services.azure.credentials import CachingCredential

    calls = 0

    class Slow:
        async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return AccessToken(f"t{calls}", int(_time.time()) + 3600)

        async def close(self) -> None:
            return None

    cred = CachingCredential(Slow())  # type: ignore[arg-type]
    tokens = await asyncio.gather(*(cred.get_token("https://management.azure.com/.default") for _ in range(20)))
    assert calls == 1 and {t.token for t in tokens} == {"t1"}
    await cred.get_token("https://management.azure.com/.default", tenant_id="other")
    assert calls == 2
    await cred.get_token("https://management.azure.com/.default", claims="challenge")
    assert calls == 3
