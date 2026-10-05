"""Mapping of Azure Resource Health availability states to platform health.

Resource Health data itself is read through Resource Graph (``healthresources``
table) in ``resource_graph.py``, which returns every resource's state in one query.
"""

from __future__ import annotations

from typing import Literal

HealthLevel = Literal["healthy", "warning", "critical", "unknown"]

AVAILABILITY_TO_HEALTH: dict[str, HealthLevel] = {
    "available": "healthy",
    "degraded": "warning",
    "unavailable": "critical",
    "unknown": "unknown",
}


def health_from_availability(state: str | None) -> HealthLevel | None:
    if not state:
        return None
    return AVAILABILITY_TO_HEALTH.get(state.lower(), "unknown")
