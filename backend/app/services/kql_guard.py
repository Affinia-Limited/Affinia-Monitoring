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

All checks run on the query with ``//`` comments removed (string literals are respected), so a
comment cannot split a forbidden token, e.g. ``workspace//x`` + newline + ``("other")``.
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


def strip_comments(query: str) -> str:
    """The query without ``//`` comments, string literals kept verbatim.

    Understands KQL string forms: '...' and "..." with backslash escapes, verbatim @'...' / @"..."
    (a doubled quote escapes), and multi-line ```...```. An unterminated string runs to the end,
    which keeps the remaining text visible to the checks.
    """
    out: list[str] = []
    i, n = 0, len(query)
    while i < n:
        if query.startswith("```", i):
            end = query.find("```", i + 3)
            end = n if end < 0 else end + 3
            out.append(query[i:end])
            i = end
        elif query[i] in "'\"":
            quote = query[i]
            verbatim = i > 0 and query[i - 1] == "@"
            j = i + 1
            while j < n:
                if not verbatim and query[j] == "\\":
                    j += 2
                    continue
                if query[j] == quote:
                    if verbatim and j + 1 < n and query[j + 1] == quote:
                        j += 2
                        continue
                    break
                j += 1
            out.append(query[i : j + 1])
            i = j + 1
        elif query.startswith("//", i):
            end = query.find("\n", i)
            i = n if end < 0 else end
        else:
            out.append(query[i])
            i += 1
    return "".join(out)


def validate_kql(query: str) -> str:
    stripped = query.strip()
    if not stripped:
        raise ValidationFailedError("The query is empty.", code="KQL_EMPTY")
    if len(stripped) > MAX_QUERY_LENGTH:
        raise ValidationFailedError("The query is too long.", code="KQL_TOO_LONG")
    code = strip_comments(stripped)
    if _CONTROL.search(code):
        raise ValidationFailedError("Management commands are not permitted.", code="KQL_FORBIDDEN")
    if match := _CROSS_SCOPE.search(code):
        raise ValidationFailedError(
            f"Cross-resource function '{match.group(1)}()' is not permitted. Queries are scoped to the "
            "selected resource.",
            code="KQL_FORBIDDEN",
        )
    if match := _EXTERNAL.search(code):
        raise ValidationFailedError(f"'{match.group(1)}' is not permitted.", code="KQL_FORBIDDEN")
    for plugin in _EVALUATE.findall(code):
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
