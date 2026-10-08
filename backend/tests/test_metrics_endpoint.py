"""The /metrics exposition stays bounded and parseable whatever URLs clients request."""

from __future__ import annotations

import uuid

import httpx

from tests.conftest import auth_headers


async def test_latency_is_labelled_by_route_template(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await client.get(f"/api/v1/no-such-path-{uuid.uuid4()}")
    await client.get("/api/v1/x%22%7D%201evil_metric%7Ba%3D%22")
    await client.get(f"/api/v1/resources/{uuid.uuid4()}", headers=auth_headers("viewer"))

    body = (await client.get("/metrics")).text
    latency = [line for line in body.splitlines() if line.startswith("amp_http_request_duration_seconds_count")]
    routes = {line.split('route="', 1)[1].split('"', 1)[0] for line in latency}
    assert "unmatched" in routes
    assert "/api/v1/resources/{resource_id}" in routes
    # No raw paths, so random URLs cannot grow the series without limit or inject text.
    assert not any("no-such-path" in r or "evil" in r for r in routes)
    assert "evil_metric" not in body
