"""Log Analytics / Application Insights log queries (real implementation).

All queries are *resource-centric* (``LogsQueryClient.query_resource``): Azure
scopes the query to data emitted by that one resource, so a query can never read
another resource's logs even if the workspace is shared. Workspace-wide queries
are issued against the workspace *resource* id, which must itself be a discovered
resource the caller is authorised for. Cross-scope KQL functions are rejected by
``app.services.kql_guard`` before any query is sent.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from azure.monitor.query import LogsQueryPartialResult
from azure.monitor.query import LogsQueryResult as SdkLogsQueryResult
from azure.monitor.query.aio import LogsQueryClient

from app.core.logging import redact
from app.services.azure.credentials import CredentialProvider
from app.services.azure.errors import azure_call
from app.services.azure.types import LogColumn, LogQueryResult, TimeRange

_SERVER_TIMEOUT_SECONDS = 60


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


class AzureLogsService:
    def __init__(self, credentials: CredentialProvider):
        self._credentials = credentials

    async def query_resource(
        self, tenant_id: str, resource_azure_id: str, kql: str, time_range: TimeRange, max_rows: int
    ) -> LogQueryResult:
        credential = self._credentials.for_tenant(tenant_id)
        async with LogsQueryClient(credential) as client:
            async with azure_call("logs.query_resource"):
                response = await client.query_resource(
                    resource_azure_id,
                    kql,
                    timespan=(time_range.start, time_range.end),
                    server_timeout=_SERVER_TIMEOUT_SECONDS,
                )

        partial_error: str | None = None
        tables: list[Any]
        if isinstance(response, LogsQueryPartialResult):
            tables = list(response.partial_data or [])
            partial_error = redact(str(getattr(response.partial_error, "message", "") or "Partial results."))[:300]
        elif isinstance(response, SdkLogsQueryResult):
            tables = list(response.tables or [])
        else:  # pragma: no cover - defensive
            tables = []

        if not tables:
            return LogQueryResult(columns=[], rows=[], partial_error=partial_error)

        table = tables[0]
        column_types = list(getattr(table, "columns_types", None) or ["string"] * len(table.columns))
        columns = [
            LogColumn(name=str(name), type=str(ctype)) for name, ctype in zip(table.columns, column_types, strict=False)
        ]
        rows = [[_jsonable(v) for v in row] for row in table.rows[: max_rows + 1]]
        truncated = len(rows) > max_rows
        return LogQueryResult(columns=columns, rows=rows[:max_rows], truncated=truncated, partial_error=partial_error)
