"""Log queries: predefined vs custom KQL, validation, and scoping."""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ValidationFailedError
from app.services.kql_guard import apply_filters, quote_kql_string, validate_kql
from tests.conftest import OTHER_TENANT, auth_headers
from tests.helpers import find_resource, seeded


@pytest.mark.parametrize(
    "query",
    [
        "workspace('other').AzureDiagnostics | take 1",
        "union app('other-app').requests",
        "resource('/subscriptions/x').AzureActivity",
        "cluster('help').database('Samples').StormEvents",
        "externaldata(x:string) [@'https://example.test/data.csv']",
        "print 1 | evaluate http_request('https://example.test')",
        "evaluate sql_request('Server=x', 'select 1')",
        ".show tables",
        "let x = 1;\n.drop table T",
        "",
        "x" * 10_001,
    ],
)
def test_kql_guard_rejects_dangerous_queries(query: str) -> None:
    with pytest.raises(ValidationFailedError):
        validate_kql(query)


@pytest.mark.parametrize(
    "query",
    [
        "AppServiceHTTPLogs | where ScStatus >= 500 | summarize Errors=count() by bin(TimeGenerated, 5m)",
        "requests | evaluate bag_unpack(customDimensions)",
        "traces | where message has 'workspace' | take 10",
    ],
)
def test_kql_guard_allows_normal_queries(query: str) -> None:
    assert validate_kql(query)


def test_filters_are_quoted_safely() -> None:
    assert quote_kql_string('a"b\\c') == '"a\\"b\\\\c"'
    query = apply_filters("T | take 10 | render timechart", 'x" | .drop', ["Error"], "Level")
    assert "render" not in query
    assert '| where * has "x\\" | .drop"' in query
    assert '| where tostring(Level) in~ ("Error")' in query


async def test_predefined_query_for_viewer_role_requires_logs_permission(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    body = {"resource_id": app["id"], "query_key": "http_logs", "time_range": "1h"}
    assert (await client.post("/api/v1/logs/query", json=body, headers=auth_headers("viewer"))).status_code == 403
    response = await client.post("/api/v1/logs/query", json=body, headers=auth_headers("operator"))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["is_mock"] is True
    assert [c["name"] for c in result["columns"]] == [
        "TimeGenerated",
        "CsMethod",
        "CsUriStem",
        "ScStatus",
        "TimeTaken",
        "CsHost",
    ]
    assert result["row_count"] > 0


async def test_related_app_insights_query_runs_against_component(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    ai = await find_resource(client, "appi-crm-prod-uks")
    response = await client.post(
        "/api/v1/logs/query",
        json={"resource_id": app["id"], "query_key": "ai_exceptions", "severities": ["Error"], "search": "timeout"},
        headers=auth_headers("operator"),
    )
    body = response.json()
    assert body["executed_against"] == ai["id"]
    assert 'where * has "timeout"' in body["query"]
    assert "tostring(severityLevel) in~" in body["query"]


async def test_custom_kql_requires_run_kql_and_is_validated(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    kql = "AppServiceHTTPLogs\n| where ScStatus >= 500\n| summarize Errors=count() by bin(TimeGenerated, 5m)"
    ok = await client.post(
        "/api/v1/logs/query",
        json={"resource_id": app["id"], "kql": kql, "time_range": "1h"},
        headers=auth_headers("operator"),
    )
    assert ok.status_code == 200, ok.text
    assert [c["name"] for c in ok.json()["columns"]] == ["TimeGenerated", "Errors"]

    blocked = await client.post(
        "/api/v1/logs/query",
        json={"resource_id": app["id"], "kql": "workspace('x').Heartbeat"},
        headers=auth_headers("operator"),
    )
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "KQL_FORBIDDEN"

    audit = (
        await client.get("/api/v1/audit-logs", params={"action": "logs.kql"}, headers=auth_headers("admin"))
    ).json()["items"]
    assert any(e["action"] == "logs.kql_executed" for e in audit)


async def test_logs_cannot_target_other_organisations(client: httpx.AsyncClient) -> None:
    await seeded(client)
    app = await find_resource(client, "app-crm-prod-uks")
    response = await client.post(
        "/api/v1/logs/query",
        json={"resource_id": app["id"], "query_key": "http_logs"},
        headers=auth_headers("super_admin", tenant=OTHER_TENANT),
    )
    assert response.status_code == 404


async def test_targets_and_queries_listing(client: httpx.AsyncClient) -> None:
    await seeded(client)
    targets = (await client.get("/api/v1/logs/targets", headers=auth_headers("operator"))).json()
    names = {t["name"] for t in targets}
    assert "app-crm-prod-uks" in names and "log-crm-prod-uks" in names
    ws = next(t for t in targets if t["name"] == "log-crm-prod-uks")
    queries = (
        await client.get(
            "/api/v1/logs/queries", params={"resource_id": ws["resource_id"]}, headers=auth_headers("operator")
        )
    ).json()
    assert {q["key"] for q in queries} == {"workspace_tables", "workspace_errors", "workspace_activity"}
