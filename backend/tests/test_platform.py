"""Overview, search, platform self-monitoring and error handling."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from tests.conftest import auth_headers
from tests.helpers import seeded


async def test_overview(client: httpx.AsyncClient) -> None:
    await seeded(client)
    body = (await client.get("/api/v1/overview", headers=auth_headers("viewer"))).json()
    assert body["is_mock"] is True
    assert body["totals"]["projects"] == 2
    assert body["totals"]["subscriptions"] == 1
    # Health covers monitored resources only; inventory items are counted separately.
    health_total = sum(body["health"][k] for k in ("healthy", "warning", "critical", "unknown"))
    assert health_total == body["totals"]["monitored_resources"]
    assert body["totals"]["monitored_resources"] + body["totals"]["inventory_resources"] == body["totals"]["resources"]
    attention = {a["name"]: a for a in body["needs_attention"]}
    assert attention["app-crm-prod-uks"]["health_status"] == "critical"
    assert "HTTP 5xx" in attention["app-crm-prod-uks"]["reason"]
    assert next(iter(attention)) == "app-crm-prod-uks"  # critical first
    assert all(c["type_display_name"] for c in body["recent_changes"])
    assert body["service_health"][0]["relevant"] is True
    names = [p["name"] for p in body["project_health"]]
    assert names == ["CRM", "PRISM"]
    prism = body["project_health"][1]
    assert {e["name"] for e in prism["environments"]} == {"Development", "Production"}
    assert body["service_health"][0]["title"].startswith("Demo advisory")
    assert body["recent_changes"] and body["recent_changes"][0]["resource_id"]


@pytest.mark.parametrize(
    ("query", "expected_kind", "expected_title"),
    [
        ("CRM", "project", "CRM"),
        ("app-crm-prod-uks", "resource", "app-crm-prod-uks"),
        ("sql-crm-prod", "resource", "sql-crm-prod-uks"),
        ("Front Door", "resource", "afd-crm-prod"),
        ("Production", "environment", "CRM / Production"),
        ("UK South", "resource", None),
        ("Demo - Line", "subscription", "Demo - Line of Business"),
    ],
)
async def test_global_search(
    client: httpx.AsyncClient, query: str, expected_kind: str, expected_title: str | None
) -> None:
    await seeded(client)
    hits = (await client.get("/api/v1/search", params={"q": query}, headers=auth_headers("viewer"))).json()["hits"]
    matching = [h for h in hits if h["kind"] == expected_kind]
    assert matching, hits
    if expected_title:
        assert expected_title in [h["title"] for h in matching]


async def test_resource_filters_and_facets(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    prod = next(e for e in data["crm"]["environments"] if e["slug"] == "prod")
    r = (
        await client.get(
            "/api/v1/resources",
            params={"project_id": data["crm"]["id"], "environment_id": prod["id"], "monitor_key": "app_service"},
            headers=auth_headers("viewer"),
        )
    ).json()
    assert [i["name"] for i in r["items"]] == ["app-crm-prod-uks"]
    facets = (await client.get("/api/v1/resources/facets", headers=auth_headers("viewer"))).json()
    assert any(f["label"] == "App Service" for f in facets["resource_types"])
    assert facets["locations"][0]["value"] == "uksouth"
    paged = (
        await client.get(
            "/api/v1/resources", params={"page_size": 5, "page": 2, "sort": "-name"}, headers=auth_headers("viewer")
        )
    ).json()
    assert len(paged["items"]) == 5 and paged["page"] == 2


async def test_platform_endpoints(client: httpx.AsyncClient) -> None:
    assert (await client.get("/live")).json() == {"status": "ok"}
    ready = await client.get("/ready")
    assert ready.status_code == 200 and ready.json()["checks"]["database"]["status"] == "ok"
    health = (await client.get("/health")).json()
    assert health["azure_provider"] == "mock"
    await client.get("/api/v1/projects")
    metrics = (await client.get("/metrics")).text
    assert "amp_http_requests_total" in metrics
    assert "amp_http_request_duration_seconds_bucket" in metrics


async def test_request_id_and_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/projects", headers={"X-Request-ID": "abc12345-client"})
    assert response.headers["x-request-id"] == "abc12345-client"
    assert response.json()["error"]["request_id"] == "abc12345-client"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    # Invalid incoming ids are replaced rather than reflected.
    response = await client.get("/live", headers={"X-Request-ID": "<script>"})
    assert response.headers["x-request-id"] != "<script>"


async def test_unhandled_errors_do_not_leak_details(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret internal detail /etc/passwd")

    monkeypatch.setattr("app.api.v1.search.all_monitors", boom)
    transport = httpx.ASGITransport(app=client._transport.app, raise_app_exceptions=False)  # type: ignore[attr-defined]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/api/v1/search", params={"q": "x"}, headers=auth_headers("viewer"))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text


def test_unsafe_modes_rejected_outside_development() -> None:
    base = {
        "entra_tenant_id": "t",
        "entra_client_id": "c",
        "entra_audience": "a",
        "environment": "production",
        "redis_url": "rediss://cache.example:6380/0",
        "database_auth": "entra",
        "database_url": "postgresql+asyncpg://app@db.example:5432/monitoring?ssl=require",
    }
    for override in (
        {"auth_mode": "dev"},
        {"azure_provider": "mock"},
        {"task_backend": "inline"},
        {"cors_origins": ["*"]},
        # Celery without Redis would silently fall back to localhost.
        {"redis_url": None},
        # The development credentials must never reach a real deployment.
        {"database_auth": "password", "database_url": "postgresql+asyncpg://monitoring:monitoring@db:5432/monitoring"},
    ):
        with pytest.raises(ValueError):
            Settings(**{**base, "azure_provider": "azure", "task_backend": "celery", **override})
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            auth_mode="entra",
            azure_provider="azure",
            task_backend="celery",
            entra_tenant_id=None,
            entra_client_id=None,
            entra_audience=None,
        )
    ok = Settings(**base, azure_provider="azure", task_backend="celery", cors_origins=["https://monitor.example"])
    assert ok.is_production


def test_environment_defaults_to_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that forgets ENVIRONMENT must not get development's relaxed rules."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("AUTH_MODE", "dev")
    with pytest.raises(ValueError, match="AUTH_MODE=dev"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_csv_settings_parse() -> None:
    s = Settings(environment="test", cors_origins="https://a.example, https://b.example")  # type: ignore[arg-type]
    assert s.cors_origins == ["https://a.example", "https://b.example"]


async def test_health_sort_is_by_severity(client: httpx.AsyncClient) -> None:
    await seeded(client)
    items = (
        await client.get(
            "/api/v1/resources",
            params={"sort": "health", "page_size": 200, "monitored_only": True},
            headers=auth_headers("viewer"),
        )
    ).json()["items"]
    order = {"critical": 0, "warning": 1, "unknown": 2, "healthy": 3}
    ranks = [order[i["health_status"]] for i in items]
    assert ranks == sorted(ranks) and ranks[0] == 0
