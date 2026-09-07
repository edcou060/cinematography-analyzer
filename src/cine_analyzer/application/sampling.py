"""Deterministic multi-purpose sample planning. No pixels, no decode."""

from uuid import UUID

from cine_analyzer.application.identity import stable_uuid
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.media import SamplePurpose, SampleRequest, SamplingPlan
from cine_analyzer.domain.shots import Shot, ShotSet
from cine_analyzer.domain.time import Rational
from cine_analyzer.domain.types import SCHEMA_VERSION

__all__ = [
    "CHROMATIC_FRACTIONS",
    "COMPOSITION_MAX_SAMPLES",
    "COMPOSITION_MIN_SAMPLES",
    "SAMPLING_METHOD_VERSION",
    "frame_duration_ms",
    "plan_samples",
]

SAMPLING_METHOD_VERSION = "sampling-v1"
# Default three chromatic targets from docs/metrics/metric-definitions.md §3.
CHROMATIC_FRACTIONS = (0.2, 0.5, 0.8)
# Architecture §8 composition clamp.
COMPOSITION_MIN_SAMPLES = 3
COMPOSITION_MAX_SAMPLES = 60


def frame_duration_ms(rate: Rational) -> int:
    """Approximate frame duration from a rational rate, integer milliseconds."""
    return max(1, int(1000 * rate.denominator / rate.numerator + 0.5))


def plan_samples(
    shot_set: ShotSet,
    *,
    video_id: UUID,
    config: AnalysisConfig,
    frame_rate: Rational,
) -> SamplingPlan:
    """Build purpose-tagged requests, deduplicated by shot and timestamp."""
    frame_ms = frame_duration_ms(frame_rate)
    collected: dict[tuple[UUID, int], list[SamplePurpose]] = {}
    order: list[tuple[UUID, int]] = []
    for shot in shot_set.shots:
        for timestamp_ms, purpose in _targets_for_shot(shot, config=config, frame_ms=frame_ms):
            key = (shot.shot_id, timestamp_ms)
            if key not in collected:
                collected[key] = []
                order.append(key)
            if purpose not in collected[key]:
                collected[key].append(purpose)
    index_by_shot = {shot.shot_id: shot.index for shot in shot_set.shots}
    requests = [
        SampleRequest(
            sample_id=stable_uuid(
                str(shot_set.analysis_id), "sample", str(shot_id), str(timestamp_ms)
            ),
            shot_id=shot_id,
            requested_ms=timestamp_ms,
            purposes=tuple(collected[(shot_id, timestamp_ms)]),
        )
        for shot_id, timestamp_ms in sorted(
            order, key=lambda item: (item[1], index_by_shot[item[0]], str(item[0]))
        )
    ]
    return SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=shot_set.analysis_id,
        video_id=video_id,
        method_version=SAMPLING_METHOD_VERSION,
        requests=tuple(requests),
    )


def _targets_for_shot(
    shot: Shot,
    *,
    config: AnalysisConfig,
    frame_ms: int,
) -> list[tuple[int, SamplePurpose]]:
    duration_ms = shot.time_range.duration_ms
    start_ms = shot.time_range.start_ms
    end_ms = shot.time_range.end_ms
    interior_start = start_ms + 2 * frame_ms
    interior_end = end_ms - 2 * frame_ms
    targets: list[tuple[int, SamplePurpose]] = [
        (
            _clamp_timestamp(
                start_ms + int(fraction * duration_ms),
                start_ms,
                end_ms,
                interior_start,
                interior_end,
            ),
            SamplePurpose.CHROMATIC,
        )
        for fraction in _chromatic_fractions(config.chromatic.samples_per_shot)
    ]
    composition_count = _clamped_count(
        duration_ms,
        sample_fps=config.spatial.sample_fps,
        minimum=COMPOSITION_MIN_SAMPLES,
        maximum=COMPOSITION_MAX_SAMPLES,
        frame_ms=frame_ms,
    )
    targets.extend(
        (
            _clamp_timestamp(timestamp_ms, start_ms, end_ms, interior_start, interior_end),
            SamplePurpose.COMPOSITION,
        )
        for timestamp_ms in _evenly_spaced(start_ms, end_ms, composition_count)
    )
    motion_count = _clamped_count(
        duration_ms,
        sample_fps=config.motion.sample_fps,
        minimum=1,
        maximum=10_000,
        frame_ms=frame_ms,
    )
    targets.extend(
        (
            _clamp_timestamp(timestamp_ms, start_ms, end_ms, interior_start, interior_end),
            SamplePurpose.MOTION,
        )
        for timestamp_ms in _evenly_spaced(start_ms, end_ms, motion_count)
    )
    midpoint = _clamp_timestamp(
        start_ms + duration_ms // 2, start_ms, end_ms, interior_start, interior_end
    )
    targets.append((midpoint, SamplePurpose.EVIDENCE))
    return targets


def _chromatic_fractions(samples_per_shot: int) -> tuple[float, ...]:
    if samples_per_shot == len(CHROMATIC_FRACTIONS):
        return CHROMATIC_FRACTIONS
    return tuple((index + 1) / (samples_per_shot + 1) for index in range(samples_per_shot))


def _clamped_count(
    duration_ms: int,
    *,
    sample_fps: float,
    minimum: int,
    maximum: int,
    frame_ms: int,
) -> int:
    duration_s = duration_ms / 1000.0
    estimated = int(duration_s * sample_fps + 0.5)
    frames_available = max(1, duration_ms // frame_ms)
    return min(max(estimated, minimum), maximum, frames_available)


def _evenly_spaced(start_ms: int, end_ms: int, count: int) -> list[int]:
    duration_ms = end_ms - start_ms
    if count <= 1:
        return [start_ms + duration_ms // 2]
    return [start_ms + int((index + 0.5) * duration_ms / count) for index in range(count)]


def _clamp_timestamp(
    raw: int,
    start_ms: int,
    end_ms: int,
    interior_start: int,
    interior_end: int,
) -> int:
    if interior_end > interior_start:
        return min(max(raw, interior_start), interior_end - 1)
    return min(max(raw, start_ms), end_ms - 1)
