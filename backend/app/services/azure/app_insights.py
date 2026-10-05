"""Application Insights helpers.

Telemetry is queried resource-centric through ``LogsService.query_resource``
against the component's ARM id; Application Insights metrics go through the
normal ``MetricsService``. This module resolves which component belongs to a
resource.
"""

from __future__ import annotations

from typing import Any


def linked_component_id(properties: dict[str, Any]) -> str | None:
    """App Services record their component in the ``hidden-link: /app-insights-resource-id`` tag.

    Discovery copies it into ``properties["appInsightsResourceId"]``.
    """
    value = properties.get("appInsightsResourceId")
    return str(value).lower() if value else None
