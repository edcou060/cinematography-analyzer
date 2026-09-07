"""Integer-millisecond timeline windows, component alignment, and inspect summaries."""

import math
from uuid import UUID

from cine_analyzer.application.cut_activity import cut_activity, internal_boundary_ms
from cine_analyzer.application.motion import MotionSeriesPoint
from cine_analyzer.application.normalize import robust_normalize
from cine_analyzer.application.tension import combine_tension, effective_weights
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.shots import ShotSet
from cine_analyzer.domain.temporal import AudioWindowValue
from cine_analyzer.domain.timeline import TENSION_METHOD_VERSION, Timeline, TimelinePoint
from cine_analyzer.domain.types import SCHEMA_VERSION

__all__ = [
    "TENSION_METHOD_VERSION",
    "build_timeline",
    "shot_index_at",
    "summarize_timeline",
    "window_starts",
]


def window_starts(duration_ms: int, hop_ms: int) -> tuple[int, ...]:
    """Inclusive starts on ``[0, duration_ms)``. The last start may be a partial window."""
    if duration_ms <= 0 or hop_ms <= 0:
        return ()
    return tuple(range(0, duration_ms, hop_ms))


def shot_index_at(at_ms: int, shot_set: ShotSet) -> int:
    """Half-open shot membership. A boundary instant belongs to the outgoing shot."""
    for shot in shot_set.shots:
        if shot.time_range.start_ms <= at_ms < shot.time_range.end_ms:
            return shot.index
    return shot_set.shots[-1].index


def build_timeline(
    *,
    analysis_id: UUID,
    shot_set: ShotSet,
    config: AnalysisConfig,
    motion_series: tuple[MotionSeriesPoint, ...],
    audio_windows: tuple[AudioWindowValue | None, ...],
    audio_available: bool,
    motion_available: bool,
    extra_warnings: tuple[str, ...] = (),
    audio_reason: str | None = None,
) -> Timeline:
    """Align cut, audio, and motion onto one hop and store every tension component."""
    duration_ms = shot_set.duration_ms()
    starts = window_starts(duration_ms, config.tension.hop_ms)
    boundaries = internal_boundary_ms(tuple(shot.time_range.start_ms for shot in shot_set.shots))
    weights, weight_warnings = effective_weights(
        config.tension.weights,
        audio_available=audio_available,
        motion_available=motion_available,
    )
    cuts = tuple(cut_activity(at_ms, boundaries, config.tension) for at_ms in starts)
    audio_raw = _audio_raw_series(audio_windows, len(starts))
    motion_raw = tuple(
        _motion_at(at_ms, shot_index_at(at_ms, shot_set), motion_series, config.tension.hop_ms)
        for at_ms in starts
    )
    if audio_available:
        audio_activity = _audio_activity(audio_raw, config)
    else:
        audio_activity = tuple(0.0 for _ in starts)
    motion_activity = (
        _motion_activity(motion_raw, config) if motion_available else tuple(0.0 for _ in starts)
    )
    points = tuple(
        TimelinePoint(
            at_ms=at_ms,
            shot_index=shot_index_at(at_ms, shot_set),
            tension=combine_tension(
                cut_activity=cuts[index],
                audio_activity=audio_activity[index],
                motion_activity=motion_activity[index],
                weights=weights,
            ),
            audio=audio_windows[index] if index < len(audio_windows) else None,
        )
        for index, at_ms in enumerate(starts)
    )
    warnings = _dedupe((*extra_warnings, *weight_warnings))
    if audio_reason and audio_reason not in warnings:
        warnings = (audio_reason, *warnings)
    return Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=analysis_id,
        hop_ms=config.tension.hop_ms,
        window_ms=config.audio.window_ms,
        method_version=TENSION_METHOD_VERSION,
        weights=config.tension.weights,
        effective_weights=weights,
        warnings=warnings,
        points=points,
    )


def summarize_timeline(timeline: Timeline) -> dict[str, object]:
    """CLI-facing tension-proxy summary. No filesystem paths."""
    return {
        "analysis_id": str(timeline.analysis_id),
        "effective_weights": timeline.effective_weights.model_dump(mode="json"),
        "hop_ms": timeline.hop_ms,
        "label": "tension proxy",
        "method_version": timeline.method_version,
        "peaks": _peaks(timeline),
        "point_count": len(timeline.points),
        "warnings": list(timeline.warnings),
        "weights": timeline.weights.model_dump(mode="json"),
        "window_ms": timeline.window_ms,
    }


def _audio_raw_series(
    windows: tuple[AudioWindowValue | None, ...],
    count: int,
) -> tuple[tuple[float, float, float], ...]:
    series: list[tuple[float, float, float]] = []
    for index in range(count):
        window = windows[index] if index < len(windows) else None
        if window is None:
            series.append((0.0, 0.0, 0.0))
            continue
        series.append(
            (
                window.onset_strength,
                window.spectral_flux,
                10.0 ** (window.rms_dbfs / 20.0),
            )
        )
    return tuple(series)


def _audio_activity(
    raw: tuple[tuple[float, float, float], ...],
    config: AnalysisConfig,
) -> tuple[float, ...]:
    onset = robust_normalize(
        tuple(item[0] for item in raw),
        percentile_low=config.tension.percentile_low,
        percentile_high=config.tension.percentile_high,
        epsilon=config.tension.epsilon,
    )
    flux = robust_normalize(
        tuple(item[1] for item in raw),
        percentile_low=config.tension.percentile_low,
        percentile_high=config.tension.percentile_high,
        epsilon=config.tension.epsilon,
    )
    rms = robust_normalize(
        tuple(item[2] for item in raw),
        percentile_low=config.tension.percentile_low,
        percentile_high=config.tension.percentile_high,
        epsilon=config.tension.epsilon,
    )
    return tuple((onset[i] + flux[i] + rms[i]) / 3.0 for i in range(len(raw)))


def _motion_activity(
    raw: tuple[tuple[float, float], ...],
    config: AnalysisConfig,
) -> tuple[float, ...]:
    global_mags = robust_normalize(
        tuple(item[0] for item in raw),
        percentile_low=config.tension.percentile_low,
        percentile_high=config.tension.percentile_high,
        epsilon=config.tension.epsilon,
    )
    residual_mags = robust_normalize(
        tuple(item[1] for item in raw),
        percentile_low=config.tension.percentile_low,
        percentile_high=config.tension.percentile_high,
        epsilon=config.tension.epsilon,
    )
    return tuple((global_mags[i] + residual_mags[i]) / 2.0 for i in range(len(raw)))


def _motion_at(
    at_ms: int,
    shot_index: int,
    series: tuple[MotionSeriesPoint, ...],
    hop_ms: int,
) -> tuple[float, float]:
    in_window = [
        item
        for item in series
        if item.shot_index == shot_index and at_ms <= item.at_ms < at_ms + hop_ms
    ]
    if in_window:
        return (
            sum(item.global_magnitude for item in in_window) / len(in_window),
            sum(item.residual_magnitude for item in in_window) / len(in_window),
        )
    in_shot = [item for item in series if item.shot_index == shot_index]
    if not in_shot:
        return (0.0, 0.0)
    nearest = min(in_shot, key=lambda item: abs(item.at_ms - at_ms))
    return (nearest.global_magnitude, nearest.residual_magnitude)


def _peaks(timeline: Timeline) -> list[dict[str, object]]:
    points = timeline.points
    if not points:
        return []
    chosen: list[int] = []
    for index, point in enumerate(points):
        value = point.tension.combined_proxy
        left = points[index - 1].tension.combined_proxy if index else -1.0
        right = points[index + 1].tension.combined_proxy if index + 1 < len(points) else -1.0
        if value >= left and value >= right and value > 0.0:
            if index and math.isclose(points[index - 1].tension.combined_proxy, value):
                continue
            chosen.append(index)
    if not chosen:
        chosen = [max(range(len(points)), key=lambda index: points[index].tension.combined_proxy)]
    return [_peak_payload(points[index]) for index in chosen]


def _peak_payload(point: TimelinePoint) -> dict[str, object]:
    return {
        "at_ms": point.at_ms,
        "audio_activity": point.tension.audio_activity,
        "combined_proxy": point.tension.combined_proxy,
        "cut_activity": point.tension.cut_activity,
        "motion_activity": point.tension.motion_activity,
    }


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)
