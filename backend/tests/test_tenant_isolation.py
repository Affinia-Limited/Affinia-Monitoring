"""An Azure subscription belongs to exactly one organisation, and only to one approved for its tenant."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.services.azure.mock.estate import MOCK_TENANT_ID
from app.services.azure.provider import get_azure_services, set_azure_services
from tests.conftest import OTHER_TENANT, TEST_TENANT, auth_headers
from tests.helpers import SUB_A, SUB_B, connect

OTHER_ADMIN = auth_headers("admin", tenant=OTHER_TENANT)


def _connection(subscriptions: list[str]) -> dict[str, Any]:
    return {"name": "Theirs", "tenant_id": MOCK_TENANT_ID, "subscription_ids": subscriptions}


async def test_subscription_cannot_be_claimed_by_another_organisation(client: httpx.AsyncClient) -> None:
    await connect(client, [SUB_A])

    claimed = await client.post("/api/v1/azure/connections", json=_connection([SUB_A]), headers=OTHER_ADMIN)
    assert claimed.status_code == 409, claimed.text
    assert claimed.json()["error"]["code"] == "SUBSCRIPTION_OWNED_ELSEWHERE"
    # Nothing leaked into the other organisation.
    resources = await client.get("/api/v1/resources", headers=auth_headers("viewer", tenant=OTHER_TENANT))
    assert resources.json()["total"] == 0

    # The picker no longer offers it, but still offers subscriptions nobody has connected.
    listed = await client.get(
        "/api/v1/azure/available-subscriptions", params={"tenant_id": MOCK_TENANT_ID}, headers=OTHER_ADMIN
    )
    ids = {s["subscription_id"] for s in listed.json()}
    assert SUB_A not in ids and SUB_B in ids

    # Adding it to an existing connection is refused the same way.
    own = await client.post("/api/v1/azure/connections", json=_connection([SUB_B]), headers=OTHER_ADMIN)
    assert own.status_code == 202, own.text
    added = await client.patch(
        f"/api/v1/azure/connections/{own.json()['connection']['id']}",
        json={"add_subscription_ids": [SUB_A]},
        headers=OTHER_ADMIN,
    )
    assert added.status_code == 409 and added.json()["error"]["code"] == "SUBSCRIPTION_OWNED_ELSEWHERE"


async def test_disconnected_subscription_can_move_to_another_organisation(client: httpx.AsyncClient) -> None:
    created = await connect(client, [SUB_A])
    deleted = await client.delete(
        f"/api/v1/azure/connections/{created['connection']['id']}", headers=auth_headers("admin")
    )
    assert deleted.status_code == 204, deleted.text
    moved = await client.post("/api/v1/azure/connections", json=_connection([SUB_A]), headers=OTHER_ADMIN)
    assert moved.status_code == 202, moved.text


@pytest.fixture
def real_azure_rules(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """The mock estate, judged by the rules that apply to real Azure (ownership by home tenant)."""
    services = get_azure_services()
    set_azure_services(replace(services, is_mock=False))
    mapping: dict[str, list[str]] = {}
    monkeypatch.setattr(get_settings(), "organization_azure_tenants", mapping)
    yield mapping
    set_azure_services(services)


async def test_subscription_from_an_unapproved_tenant_is_refused(
    client: httpx.AsyncClient, real_azure_rules: dict[str, list[str]]
) -> None:
    # The mock subscriptions live in MOCK_TENANT_ID, which is not this organisation's Entra tenant.
    refused = await client.post("/api/v1/azure/connections", json=_connection([SUB_A]), headers=auth_headers("admin"))
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "SUBSCRIPTION_TENANT_NOT_ALLOWED"
    listed = await client.get(
        "/api/v1/azure/available-subscriptions", params={"tenant_id": MOCK_TENANT_ID}, headers=auth_headers("admin")
    )
    assert listed.json() == []

    # A platform operator approves the tenant for this organisation only.
    real_azure_rules[TEST_TENANT] = [MOCK_TENANT_ID]
    allowed = await client.post("/api/v1/azure/connections", json=_connection([SUB_A]), headers=auth_headers("admin"))
    assert allowed.status_code == 202, allowed.text
    other = await client.post("/api/v1/azure/connections", json=_connection([SUB_B]), headers=OTHER_ADMIN)
    assert other.status_code == 403
