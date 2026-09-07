"""HTTP-only dashboard helpers. Importing this package loads no CV libraries."""

from cine_analyzer.dashboard.client import (
    DASHBOARD_TIMELINE_MAX_POINTS,
    AnalyzerClient,
    DashboardClientError,
)
from cine_analyzer.dashboard.copy import CAVEATS, PAGE_TITLE, SYNC_LIMITATION
from cine_analyzer.dashboard.transforms import (
    KIND_ESTIMATED,
    KIND_INTERPRETED,
    KIND_MEASURED,
    KIND_UNAVAILABLE,
    format_timecode,
)

__all__ = [
    "CAVEATS",
    "DASHBOARD_TIMELINE_MAX_POINTS",
    "KIND_ESTIMATED",
    "KIND_INTERPRETED",
    "KIND_MEASURED",
    "KIND_UNAVAILABLE",
    "PAGE_TITLE",
    "SYNC_LIMITATION",
    "AnalyzerClient",
    "DashboardClientError",
    "format_timecode",
]
