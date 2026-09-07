"""Disk headroom before ingest writes."""

import shutil
from pathlib import Path

from cine_analyzer.application.errors import ingest_error

__all__ = ["ensure_disk_headroom"]


def ensure_disk_headroom(path: Path, min_free_bytes: int, *, request_id: str) -> None:
    """Fail ingest when the volume holding ``path`` is below the reserve.

    ``min_free_bytes <= 0`` disables the check (unit tests and operators who
    opt out).
    """
    if min_free_bytes <= 0:
        return
    try:
        free = shutil.disk_usage(path).free
    except OSError as error:
        raise ingest_error(
            "RESOURCE_DISK",
            "disk free space could not be measured",
            request_id=request_id,
            retryable=True,
        ) from error
    if free < min_free_bytes:
        raise ingest_error(
            "RESOURCE_DISK",
            "disk free space is below the configured reserve",
            request_id=request_id,
            retryable=True,
        )
