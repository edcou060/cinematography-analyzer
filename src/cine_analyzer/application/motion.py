"""Shot-bounded motion: adjacent pairs only, global vs residual, no camera labels."""

import math
from dataclasses import dataclass, replace
from itertools import pairwise
from uuid import UUID

from cine_analyzer.application.sample_frames import load_decoded_jpegs
from cine_analyzer.domain.artifacts import MethodProvenance
from cine_analyzer.domain.media import SamplePurpose, SamplingManifest
from cine_analyzer.domain.spatial import BoxNorm, SubjectObservation
from cine_analyzer.domain.temporal import TemporalMeasurement, TemporalValue
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.ingestion import ArtifactStore
from cine_analyzer.ports.motion import (
    FlowPairStats,
    MotionFrame,
    MotionPairInput,
)

__all__ = [
    "MOTION_METHOD_VERSION",
    "MotionSeriesPoint",
    "ShotMotionResult",
    "adjacent_motion_pairs",
    "attach_subject_boxes",
    "boxes_for_samples",
    "collect_motion_frames",
    "summarize_shot_motion",
    "wrap_temporal_measurement",
]

MOTION_METHOD_VERSION = "motion-v1"
CUT_LIKE_WARNING = "cut_like_flow_discontinuity"
_MIN_DIRECTION_PAIRS = 2


@dataclass(frozen=True, slots=True)
class MotionSeriesPoint:
    """Pair midpoint used to align motion onto the tension hop."""

    at_ms: int
    shot_index: int
    global_magnitude: float
    residual_magnitude: float


@dataclass(frozen=True, slots=True)
class ShotMotionResult:
    """Per-shot temporal envelope plus the pair series for timeline alignment."""

    measurement: TemporalMeasurement
    series: tuple[MotionSeriesPoint, ...]
    flagged_discontinuity: bool


def collect_motion_frames(
    manifest: SamplingManifest,
    sample_keys: dict[UUID, str],
    store: ArtifactStore,
    shot_id: UUID,
) -> tuple[MotionFrame, ...]:
    """Load decoded motion JPEGs for one shot with presentation timestamps."""
    decoded_ms = {
        result.sample_id: result.decoded_ms
        for result in manifest.results
        if result.shot_id == shot_id and result.decoded_ms is not None
    }
    frames: list[MotionFrame] = []
    for sample_id, jpeg in load_decoded_jpegs(
        manifest, sample_keys, store, shot_id, SamplePurpose.MOTION
    ):
        timestamp = decoded_ms.get(sample_id)
        if timestamp is None:
            continue
        frames.append(MotionFrame(sample_id=sample_id, jpeg=jpeg, decoded_ms=timestamp))
    return tuple(frames)


def adjacent_motion_pairs(frames: tuple[MotionFrame, ...]) -> tuple[MotionPairInput, ...]:
    """Consecutive samples only. Caller must pass frames from a single shot."""
    pairs: list[MotionPairInput] = []
    for left, right in pairwise(frames):
        dt_ms = right.decoded_ms - left.decoded_ms
        if dt_ms <= 0:
            continue
        pairs.append(
            MotionPairInput(
                sample_id_a=left.sample_id,
                sample_id_b=right.sample_id,
                jpeg_a=left.jpeg,
                jpeg_b=right.jpeg,
                dt_ms=dt_ms,
                at_ms=left.decoded_ms + dt_ms // 2,
                subject_boxes=(),
            )
        )
    return tuple(pairs)


def attach_subject_boxes(
    pair: MotionPairInput,
    observations: tuple[SubjectObservation, ...],
) -> MotionPairInput:
    """Copy a pair with subject boxes from either sample. Works with an empty observation list."""
    boxes = boxes_for_samples(observations, (pair.sample_id_a, pair.sample_id_b))
    return replace(pair, subject_boxes=boxes)


def boxes_for_samples(
    observations: tuple[SubjectObservation, ...],
    sample_ids: tuple[UUID, ...],
) -> tuple[BoxNorm, ...]:
    """Union of subject boxes on either sample of a pair."""
    wanted = set(sample_ids)
    return tuple(item.box for item in observations if item.sample_id in wanted)


def summarize_shot_motion(
    *,
    duration_ms: int,
    shot_index: int,
    pairs: tuple[FlowPairStats, ...],
    evidence_sample_ids: tuple[UUID, ...],
    method: MethodProvenance,
) -> ShotMotionResult:
    """Median/p90 global and residual magnitudes. Flagged pairs stay out of the median."""
    unflagged = tuple(item for item in pairs if not item.flagged_discontinuity)
    valid_ratios = tuple(item.valid_ratio for item in pairs)
    global_mags = tuple(item.global_magnitude for item in unflagged)
    residual_mags = tuple(item.residual_magnitude_median for item in unflagged)
    residual_p90s = tuple(item.residual_magnitude_p90 for item in unflagged)
    value = TemporalValue(
        duration_ms=duration_ms,
        motion_magnitude_median=_median(residual_mags),
        global_motion_magnitude=_median(global_mags),
        residual_motion_magnitude=_median(residual_mags),
        motion_magnitude_p90=_median(residual_p90s),
        flow_valid_ratio=_median(valid_ratios),
        direction_consistency=_direction_consistency(unflagged),
    )
    series = tuple(
        MotionSeriesPoint(
            at_ms=item.at_ms,
            shot_index=shot_index,
            global_magnitude=item.global_magnitude,
            residual_magnitude=item.residual_magnitude_median,
        )
        for item in unflagged
    )
    return ShotMotionResult(
        measurement=wrap_temporal_measurement(
            value,
            evidence_sample_ids=evidence_sample_ids,
            method=method,
        ),
        series=series,
        flagged_discontinuity=any(item.flagged_discontinuity for item in pairs),
    )


def wrap_temporal_measurement(
    value: TemporalValue,
    *,
    evidence_sample_ids: tuple[UUID, ...],
    method: MethodProvenance,
) -> TemporalMeasurement:
    """Duration is always present; motion fields may be None."""
    return TemporalMeasurement(
        status=MetricStatus.OK,
        value=value,
        evidence_sample_ids=evidence_sample_ids,
        method=method,
    )


def _median(values: tuple[float, ...]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _direction_consistency(pairs: tuple[FlowPairStats, ...]) -> float | None:
    if len(pairs) < _MIN_DIRECTION_PAIRS:
        return None
    scores: list[float] = []
    for left, right in pairwise(pairs):
        left_n = math.hypot(left.global_dx, left.global_dy)
        right_n = math.hypot(right.global_dx, right.global_dy)
        if left_n <= 0.0 or right_n <= 0.0:
            scores.append(0.0)
            continue
        cosine = (left.global_dx * right.global_dx + left.global_dy * right.global_dy) / (
            left_n * right_n
        )
        scores.append(max(0.0, min(1.0, cosine)))
    return sum(scores) / len(scores)
