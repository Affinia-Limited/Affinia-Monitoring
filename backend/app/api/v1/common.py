from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query

from app.services.azure.types import TimeRange


def time_range_param(
    time_range: Annotated[str, Query(alias="timeRange", pattern=r"^(30m|1h|6h|24h|7d|30d|custom)$")] = "24h",
    start: datetime | None = None,
    end: datetime | None = None,
) -> TimeRange:
    return TimeRange.from_params(time_range, start, end)


TimeRangeDep = Annotated[TimeRange, Depends(time_range_param)]
