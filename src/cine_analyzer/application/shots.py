"""Build a validated ShotSet from internal detector boundaries.

The detector reports edits. This module adds clip start/end, merges sub-minimum
intervals, and emits domain shots — never narrative scenes.
"""

from datetime import datetime
from itertools import pairwise
from uuid import UUID

from cine_analyzer.application.identity import stable_uuid
from cine_analyzer.domain.artifacts import MethodProvenance
from cine_analyzer.domain.shots import Shot, ShotBoundary, ShotSet
from cine_analyzer.domain.time import TimeRangeMs
from cine_analyzer.domain.types import SCHEMA_VERSION
from cine_analyzer.ports.shots import DetectedBoundary

__all__ = [
    "SHOTS_METHOD_VERSION",
    "boundaries_to_shot_set",
    "merge_short_ranges",
    "shot_provenance",
]

SHOTS_METHOD_VERSION = "shots-v1"


def merge_short_ranges(
    ranges: tuple[TimeRangeMs, ...], *, min_shot_ms: int
) -> tuple[TimeRangeMs, ...]:
    """Merge intervals shorter than ``min_shot_ms`` into a neighbour.

    A short shot merges into the following shot when one exists, otherwise into
    the previous shot. A single remaining interval is kept even if it is short.
    """
    merged = list(ranges)
    changed = True
    while changed and len(merged) > 1:
        changed = False
        for index, interval in enumerate(merged):
            if interval.duration_ms >= min_shot_ms:
                continue
            if index < len(merged) - 1:
                combined = TimeRangeMs(start_ms=interval.start_ms, end_ms=merged[index + 1].end_ms)
                merged = [*merged[:index], combined, *merged[index + 2 :]]
            else:
                combined = TimeRangeMs(start_ms=merged[index - 1].start_ms, end_ms=interval.end_ms)
                merged = [*merged[: index - 1], combined]
            changed = True
            break
    return tuple(merged)


def boundaries_to_shot_set(
    boundaries: tuple[DetectedBoundary, ...],
    *,
    analysis_id: UUID,
    duration_ms: int,
    min_shot_ms: int,
    provenance: MethodProvenance,
) -> ShotSet:
    """Force outer bounds, merge short shots, and assign deterministic ids."""
    cuts = _internal_positions(boundaries, duration_ms=duration_ms)
    edges = (0, *cuts, duration_ms)
    ranges = tuple(TimeRangeMs(start_ms=start, end_ms=end) for start, end in pairwise(edges))
    ranges = merge_short_ranges(ranges, min_shot_ms=min_shot_ms)
    by_position = {
        item.position_ms: item for item in boundaries if 0 < item.position_ms < duration_ms
    }
    shots: list[Shot] = []
    for index, interval in enumerate(ranges):
        incoming = _boundary_at(
            interval.start_ms,
            analysis_id=analysis_id,
            by_position=by_position,
        )
        outgoing = _boundary_at(
            interval.end_ms,
            analysis_id=analysis_id,
            by_position=by_position,
        )
        shots.append(
            Shot(
                shot_id=stable_uuid(str(analysis_id), "shot", str(index)),
                index=index,
                time_range=interval,
                incoming_boundary_id=None if incoming is None else incoming.boundary_id,
                outgoing_boundary_id=None if outgoing is None else outgoing.boundary_id,
                representative_sample_id=None,
            )
        )
    return ShotSet(
        schema_version=SCHEMA_VERSION,
        analysis_id=analysis_id,
        detector=provenance,
        shots=tuple(shots),
    )


def shot_provenance(
    *,
    config_hash: str,
    code_revision: str,
    method: str,
    started_at: datetime,
    completed_at: datetime,
) -> MethodProvenance:
    """Provenance envelope for a shot-detection run."""
    return MethodProvenance(
        method=method,
        method_version=SHOTS_METHOD_VERSION,
        config_hash=config_hash,
        code_revision=code_revision,
        started_at=started_at,
        completed_at=completed_at,
    )


def _internal_positions(
    boundaries: tuple[DetectedBoundary, ...], *, duration_ms: int
) -> tuple[int, ...]:
    seen: set[int] = set()
    ordered: list[int] = []
    for item in sorted(boundaries, key=lambda boundary: boundary.position_ms):
        if item.position_ms <= 0 or item.position_ms >= duration_ms:
            continue
        if item.position_ms in seen:
            continue
        seen.add(item.position_ms)
        ordered.append(item.position_ms)
    return tuple(ordered)


def _boundary_at(
    position_ms: int,
    *,
    analysis_id: UUID,
    by_position: dict[int, DetectedBoundary],
) -> ShotBoundary | None:
    detected = by_position.get(position_ms)
    if detected is None:
        return None
    return ShotBoundary(
        boundary_id=stable_uuid(str(analysis_id), "boundary", str(position_ms)),
        position_ms=position_ms,
        transition=detected.transition,
        detector_score=detected.detector_score,
    )
