"""Demo data only exists when someone deliberately connects the demo estate, and disappears with real Azure."""

from __future__ import annotations

import httpx

from app.db.session import session_scope
from app.services.connections import archive_demo_connections
from tests.conftest import auth_headers
from tests.helpers import connect

ADMIN = auth_headers("admin")


async def test_no_demo_data_unless_connected(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/azure/connections", headers=ADMIN)).json() == []
    assert (await client.get("/api/v1/resources", headers=ADMIN)).json()["total"] == 0


async def test_demo_connection_is_flagged_and_removable(client: httpx.AsyncClient) -> None:
    created = await connect(client)
    [listed] = (await client.get("/api/v1/azure/connections", headers=ADMIN)).json()
    assert listed["is_demo"] is True
    assert (await client.get("/api/v1/resources", headers=ADMIN)).json()["total"] > 0

    response = await client.delete(f"/api/v1/azure/connections/{created['connection']['id']}", headers=ADMIN)
    assert response.status_code == 204
    assert (await client.get("/api/v1/azure/connections", headers=ADMIN)).json() == []
    assert (await client.get("/api/v1/resources", headers=ADMIN)).json()["total"] == 0
    overview = (await client.get("/api/v1/overview", headers=ADMIN)).json()
    assert overview["totals"]["resources"] == 0 and overview["totals"]["connections"] == 0


async def test_switching_to_real_azure_archives_demo_connections(client: httpx.AsyncClient) -> None:
    await connect(client)
    async with session_scope() as db:
        removed = await archive_demo_connections(db)
    assert removed == 1
    assert (await client.get("/api/v1/azure/connections", headers=ADMIN)).json() == []
    assert (await client.get("/api/v1/resources", headers=ADMIN)).json()["total"] == 0
    logs = (
        await client.get("/api/v1/audit-logs", params={"action": "azure.connection.disconnected"}, headers=ADMIN)
    ).json()["items"]
    assert logs and logs[0]["actor"] == "system" and "real Azure" in logs[0]["details"]["reason"]

    # Running it again (every start-up) is a no-op.
    async with session_scope() as db:
        assert await archive_demo_connections(db) == 0
