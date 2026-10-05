"""Validation of user-supplied KQL before it is sent to Azure.

Defence in depth on top of resource-centric execution (Azure already scopes a
resource-centric query to that resource's data):

* management/control commands (``.show``, ``.set`` ...) are rejected
* cross-scope functions (``workspace()``, ``app()``, ``resource()``, ``cluster()``,
  ``database()``, ``adx()``) are rejected, so a query cannot reach other workspaces
  the platform identity might be able to read
* external data access (``externaldata``, ``external_table``) is rejected
* ``evaluate`` is limited to an allow-list of pure analytic plugins
  (blocking ``http_request``, ``sql_request`` and similar)
* query length is bounded
"""

from __future__ import annotations

import re

from app.core.errors import ValidationFailedError

MAX_QUERY_LENGTH = 10_000

_CROSS_SCOPE = re.compile(r"\b(workspace|app|resource|cluster|database|adx|arg|entity_group)\s*\(", re.I)
_EXTERNAL = re.compile(r"\b(externaldata|external_table|materialized_view)\b", re.I)
_EVALUATE = re.compile(r"\bevaluate\s+(\w+)", re.I)
_CONTROL = re.compile(r"(^|[;\n])\s*\.", re.M)
_ALLOWED_PLUGINS = {
    "bag_unpack",
    "pivot",
    "narrow",
    "autocluster",
    "basket",
    "diffpatterns",
    "percentiles_array",
    "series_fit_poly",
}


def validate_kql(query: str) -> str:
    stripped = query.strip()
    if not stripped:
        raise ValidationFailedError("The query is empty.", code="KQL_EMPTY")
    if len(stripped) > MAX_QUERY_LENGTH:
        raise ValidationFailedError("The query is too long.", code="KQL_TOO_LONG")
    if _CONTROL.search(stripped):
        raise ValidationFailedError("Management commands are not permitted.", code="KQL_FORBIDDEN")
    if match := _CROSS_SCOPE.search(stripped):
        raise ValidationFailedError(
            f"Cross-resource function '{match.group(1)}()' is not permitted. Queries are scoped to the "
            "selected resource.",
            code="KQL_FORBIDDEN",
        )
    if match := _EXTERNAL.search(stripped):
        raise ValidationFailedError(f"'{match.group(1)}' is not permitted.", code="KQL_FORBIDDEN")
    for plugin in _EVALUATE.findall(stripped):
        if plugin.lower() not in _ALLOWED_PLUGINS:
            raise ValidationFailedError(f"The '{plugin}' plugin is not permitted.", code="KQL_FORBIDDEN")
    return stripped


def quote_kql_string(value: str) -> str:
    """Safely embed user text as a KQL string literal."""
    if len(value) > 200:
        raise ValidationFailedError("Search text is too long.")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{escaped}"'


def apply_filters(query: str, search: str | None, severities: list[str] | None, severity_column: str | None) -> str:
    """Append search / severity filters to a query without string-concatenating raw user input."""
    parts = [query.rstrip().rstrip(";")]
    # `render` must be last; drop it (the UI renders results itself).
    parts[0] = re.sub(r"\|\s*render\b[^|]*$", "", parts[0]).rstrip()
    if severities and severity_column:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", severity_column):  # defensive; plugin-defined
            raise ValidationFailedError("Invalid severity column.")
        values = ", ".join(quote_kql_string(s) for s in severities[:10])
        parts.append(f"| where tostring({severity_column}) in~ ({values})")
    if search:
        parts.append(f"| where * has {quote_kql_string(search)}")
    return "\n".join(parts)
