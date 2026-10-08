"""Alert lifecycle, job robustness, sync-run concurrency, input validation and notification safety."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from azure.core.exceptions import ServiceResponseError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AzureError, AzureThrottledError
from app.db.session import session_scope
from app.models import Alert, AzureConnection, Resource, SyncRun
from app.services.alerts.evaluator import evaluate_alert_rules
from app.services.azure.errors import azure_call
from app.services.azure.provider import get_azure_services
from tests.conftest import auth_headers
from tests.helpers import find_resource, seeded


async def _org_id(client: httpx.AsyncClient) -> uuid.UUID:
    me = (await client.get("/api/v1/auth/me", headers=auth_headers("admin"))).json()
    return uuid.UUID(me["organization_id"])


async def _firing_rule(client: httpx.AsyncClient, data: dict[str, Any], **overrides: object) -> dict[str, Any]:
    """PRISM production's app runs hot in the demo estate, so a 70% plan CPU rule fires."""
    prod = next(e for e in data["prism"]["environments"] if e["slug"] == "prod")
    body = {
        "name": "High plan CPU",
        "monitor_key": "app_service",
        "metric_name": "plan_cpu",
        "aggregation": "Average",
        "operator": "gt",
        "threshold": 70,
        "severity": "critical",
        "window_minutes": 15,
        "project_id": data["prism"]["id"],
        "environment_id": prod["id"],
        **overrides,
    }
    response = await client.post("/api/v1/alert-rules", json=body, headers=auth_headers("admin"))
    assert response.status_code == 201, response.text
    return {**response.json(), "_body": body}


async def _evaluate(client: httpx.AsyncClient) -> dict[str, int]:
    org = await _org_id(client)
    async with session_scope() as db:
        return await evaluate_alert_rules(db, get_azure_services(), org)


async def _open_alerts(client: httpx.AsyncClient) -> int:
    page = (await client.get("/api/v1/alerts", params={"status": "active"}, headers=auth_headers("viewer"))).json()
    return int(page["total"])


async def _overview_active(client: httpx.AsyncClient) -> int:
    return int((await client.get("/api/v1/overview", headers=auth_headers("viewer"))).json()["alerts"]["active"])


# ---- alert lifecycle -------------------------------------------------------------------------


async def test_deleting_a_rule_closes_its_alerts(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    rule = await _firing_rule(client, data)
    assert (await _evaluate(client))["fired"] == 1
    assert await _overview_active(client) == 1

    deleted = await client.delete(f"/api/v1/alert-rules/{rule['id']}", headers=auth_headers("admin"))
    assert deleted.status_code == 204
    assert await _open_alerts(client) == 0
    assert await _overview_active(client) == 0


async def test_disabling_a_rule_closes_its_alerts(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    rule = await _firing_rule(client, data)
    await _evaluate(client)
    body = {**rule["_body"], "enabled": False}
    updated = await client.put(f"/api/v1/alert-rules/{rule['id']}", json=body, headers=auth_headers("admin"))
    assert updated.status_code == 200, updated.text
    assert await _open_alerts(client) == 0


async def test_alerts_close_when_the_rule_no_longer_applies(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    await _firing_rule(client, data)
    await _evaluate(client)
    # The resource leaves Azure (soft-deleted by a sync): the next evaluation closes its alert.
    app = await find_resource(client, "app-prism-prod-uks")
    async with session_scope() as db:
        resource = await db.get(Resource, uuid.UUID(app["id"]))
        assert resource is not None
        resource.deleted_at = datetime.now(UTC)
    stats = await _evaluate(client)
    assert stats["closed"] == 1
    assert await _open_alerts(client) == 0


async def test_disconnecting_closes_alerts_of_its_resources(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    await _firing_rule(client, data)
    await _evaluate(client)
    removed = await client.delete(
        f"/api/v1/azure/connections/{data['connection']['id']}", headers=auth_headers("admin")
    )
    assert removed.status_code == 204
    assert await _open_alerts(client) == 0
    assert await _overview_active(client) == 0


async def test_only_one_open_alert_per_condition(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    await _firing_rule(client, data)
    await _evaluate(client)
    org = await _org_id(client)
    async with session_scope() as db:
        existing = await db.scalar(select(Alert).where(Alert.organization_id == org))
        assert existing is not None
        duplicate = Alert(
            organization_id=org,
            rule_id=existing.rule_id,
            resource_id=existing.resource_id,
            fingerprint=existing.fingerprint,
            severity="critical",
            status="active",
            title="duplicate",
            started_at=datetime.now(UTC),
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


async def test_notifications_are_sent_only_after_the_alert_is_saved(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await seeded(client)
    await _firing_rule(client, data)
    seen: list[bool] = []

    async def recording_notify(db: Any, alert: Alert, *args: Any) -> None:
        # Read from a separate session: only committed rows are visible there.
        async with session_scope() as other:
            seen.append(await other.get(Alert, alert.id) is not None)

    monkeypatch.setattr("app.services.alerts.evaluator.notify", recording_notify)
    await _evaluate(client)
    assert seen == [True]


# ---- Azure failures --------------------------------------------------------------------------


async def test_azure_read_timeouts_become_application_errors() -> None:
    with pytest.raises(AzureError) as caught:
        async with azure_call("metrics.query"):
            raise ServiceResponseError("read timed out")
    assert caught.value.code == "AZURE_UNREACHABLE"


async def test_health_job_continues_after_one_organisation_fails(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.health import evaluator

    evaluated: list[uuid.UUID] = []
    calls = 0

    async def flaky(db: Any, azure: Any, org_id: uuid.UUID, **_: Any) -> dict[str, int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        evaluated.append(org_id)
        return {}

    monkeypatch.setattr(evaluator, "evaluate_resources", flaky)
    with pytest.raises(RuntimeError, match="1 organisation"):
        await evaluator.run_health_job()
    assert len(evaluated) >= 1  # the test database has two organisations


async def test_throttled_metrics_keep_the_previous_findings(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seeded(client)
    plan = await find_resource(client, "asp-prism-prod-uks")
    assert plan["health_status"] == "warning"
    reasons = [r for r in plan["health_reasons"] if r["signal"] == "metric"]
    assert reasons

    async def throttled(*args: Any, **kwargs: Any) -> Any:
        raise AzureThrottledError()

    monkeypatch.setattr(get_azure_services().metrics, "query", throttled)
    from app.core.cache import get_cache

    await get_cache().delete_prefix("amp:metrics")
    evaluated = (
        await client.post(f"/api/v1/resources/{plan['id']}/health/evaluate", headers=auth_headers("operator"))
    ).json()
    assert evaluated["health_status"] == "warning"
    assert [r["metric"] for r in evaluated["health_reasons"] if r["signal"] == "metric"] == [
        r["metric"] for r in reasons
    ]


# ---- sync runs -------------------------------------------------------------------------------


async def test_concurrent_sync_requests_share_one_run(client: httpx.AsyncClient) -> None:
    from app.services.discovery import queue_sync_run

    data = await seeded(client)
    async with session_scope() as db:
        connection = await db.get(AzureConnection, uuid.UUID(data["connection"]["id"]))
        assert connection is not None
        first, created = await queue_sync_run(db, connection, "manual")
        second, created_again = await queue_sync_run(db, connection, "manual")
    assert created and not created_again and first.id == second.id
    # The database refuses a second active run even if the check is bypassed.
    async with session_scope() as db:
        db.add(
            SyncRun(
                organization_id=first.organization_id,
                connection_id=first.connection_id,
                trigger="manual",
                status="queued",
                steps=[],
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


async def test_abandoned_running_sync_is_replaced_and_resumed(client: httpx.AsyncClient) -> None:
    from app.services.discovery import queue_sync_run, run_sync_job

    data = await seeded(client)
    async with session_scope() as db:
        connection = await db.get(AzureConnection, uuid.UUID(data["connection"]["id"]))
        assert connection is not None
        run, _ = await queue_sync_run(db, connection, "manual")
        # The worker running it died 30 minutes ago.
        run.status = "running"
        run.heartbeat_at = datetime.now(UTC) - timedelta(minutes=30)
        run_id = run.id

    # A redelivered task starts it again instead of skipping it.
    await run_sync_job(str(run_id))
    async with session_scope() as db:
        resumed = await db.get(SyncRun, run_id)
        assert resumed is not None and resumed.status == "succeeded"

    # A manual sync request does not wait on a run whose job stopped saving progress.
    async with session_scope() as db:
        connection = await db.get(AzureConnection, uuid.UUID(data["connection"]["id"]))
        assert connection is not None
        stuck, _ = await queue_sync_run(db, connection, "manual")
        stuck.status, stuck.heartbeat_at = "running", datetime.now(UTC) - timedelta(minutes=30)
        stuck_id = stuck.id
    response = await client.post(
        f"/api/v1/azure/connections/{data['connection']['id']}/sync", headers=auth_headers("operator")
    )
    assert response.status_code == 202 and response.json()["id"] != str(stuck_id)


# ---- validation ------------------------------------------------------------------------------


async def test_partial_updates_reject_nulls_and_clean_tags(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    crm = data["crm"]
    for body in ({"name": None}, {"tag_values": None}, {"description": None}):
        response = await client.patch(f"/api/v1/projects/{crm['id']}", json=body, headers=auth_headers("admin"))
        assert response.status_code == 422, (body, response.text)
    cleaned = await client.patch(
        f"/api/v1/projects/{crm['id']}", json={"tag_values": [" crm ", "CRM", ""]}, headers=auth_headers("admin")
    )
    assert cleaned.status_code == 200 and cleaned.json()["tag_values"] == ["crm"]
    env = crm["environments"][0]
    bad_env = await client.patch(
        f"/api/v1/projects/{crm['id']}/environments/{env['id']}", json={"kind": None}, headers=auth_headers("admin")
    )
    assert bad_env.status_code == 422
    bad_conn = await client.patch(
        f"/api/v1/azure/connections/{data['connection']['id']}",
        json={"sync_enabled": None},
        headers=auth_headers("admin"),
    )
    assert bad_conn.status_code == 422


async def test_resource_search_treats_wildcards_literally(client: httpx.AsyncClient) -> None:
    await seeded(client)
    for term in ("%", "_"):
        page = (await client.get("/api/v1/resources", params={"q": term}, headers=auth_headers("viewer"))).json()
        assert page["total"] == 0, term


async def test_alert_rule_scope_must_be_live_and_consistent(client: httpx.AsyncClient) -> None:
    data = await seeded(client)
    crm_prod = next(e for e in data["crm"]["environments"] if e["slug"] == "prod")
    mismatch = await client.post(
        "/api/v1/alert-rules",
        json={
            "name": "Mismatch",
            "monitor_key": "app_service",
            "metric_name": "plan_cpu",
            "operator": "gt",
            "threshold": 70,
            "project_id": data["prism"]["id"],
            "environment_id": crm_prod["id"],
        },
        headers=auth_headers("admin"),
    )
    assert mismatch.status_code == 422
    deleted = await client.delete(f"/api/v1/projects/{data['crm']['id']}", headers=auth_headers("admin"))
    assert deleted.status_code == 204
    gone = await client.post(
        "/api/v1/alert-rules",
        json={
            "name": "Gone",
            "monitor_key": "app_service",
            "metric_name": "plan_cpu",
            "operator": "gt",
            "threshold": 70,
            "project_id": data["crm"]["id"],
        },
        headers=auth_headers("admin"),
    )
    assert gone.status_code == 422


# ---- notification channels -------------------------------------------------------------------


async def test_channel_secrets_must_belong_to_the_organisation(client: httpx.AsyncClient) -> None:
    foreign = await client.post(
        "/api/v1/notification-channels",
        json={"name": "Theirs", "channel_type": "teams", "secret_ref": "org-1-teams-ops"},
        headers=auth_headers("admin"),
    )
    assert foreign.status_code == 422
    assert "org-0-" in foreign.json()["error"]["message"]
    own = await client.post(
        "/api/v1/notification-channels",
        json={"name": "Ours", "channel_type": "teams", "secret_ref": "org-0-teams-ops"},
        headers=auth_headers("admin"),
    )
    assert own.status_code == 201


async def test_channel_test_does_not_reveal_secret_details(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def create(ref: str) -> str:
        response = await client.post(
            "/api/v1/notification-channels",
            json={"name": ref, "channel_type": "webhook", "secret_ref": ref},
            headers=auth_headers("admin"),
        )
        assert response.status_code == 201, response.text
        return str(response.json()["id"])

    monkeypatch.setenv("SECRET_ORG_0_PLAIN_HTTP", "http://example.test/hook")
    messages = set()
    for channel_id in (await create("org-0-missing"), await create("org-0-plain-http")):
        result = (
            await client.post(f"/api/v1/notification-channels/{channel_id}/test", headers=auth_headers("admin"))
        ).json()
        assert result["status"] == "failed"
        messages.add(result["message"])
    assert len(messages) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://10.1.2.3/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/hook",
        "https://192.168.0.10/hook",
        "https://localhost/hook",
    ],
)
async def test_webhooks_to_internal_addresses_are_refused(url: str) -> None:
    from app.services.alerts.channels.registry import DeliveryRefusedError, check_public_destination

    with pytest.raises(DeliveryRefusedError):
        await check_public_destination(url)


async def test_webhooks_to_public_addresses_are_allowed() -> None:
    from app.services.alerts.channels.registry import check_public_destination

    await check_public_destination("https://8.8.8.8/hook")


# ---- workers ---------------------------------------------------------------------------------


def test_worker_tasks_release_loop_bound_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import cache
    from app.workers import tasks

    released: list[str] = []

    async def fake_dispose() -> None:
        released.append("db")

    async def fake_close() -> None:
        released.append("azure")

    class ClosableCache(cache.MemoryCache):
        async def close(self) -> None:
            released.append("cache")

    monkeypatch.setattr("app.db.session.dispose_engine", fake_dispose)
    monkeypatch.setattr("app.services.azure.provider.close_azure_services", fake_close)
    previous = cache.get_cache()
    cache.set_cache(ClosableCache())

    async def job() -> int:
        return 7

    try:
        # Celery runs each task with asyncio.run; do the same in a thread so pytest's loop is untouched.
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(lambda: tasks._run(job())).result() == 7
        assert released == ["db", "cache", "azure"]
        assert cache._cache is None
    finally:
        cache.set_cache(previous)
