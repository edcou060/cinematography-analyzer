"""Presentation helpers. Convert integer milliseconds only here."""

from dataclasses import dataclass
from uuid import UUID

from cine_analyzer.api.schemas import TimelineWindowResponse
from cine_analyzer.dashboard.client import DASHBOARD_TIMELINE_MAX_POINTS
from cine_analyzer.domain.chromatics import ColorSwatch
from cine_analyzer.domain.critic import CriticInput
from cine_analyzer.domain.jobs import AnalysisState, AnalysisStatusResponse, analysis_is_terminal
from cine_analyzer.domain.report import (
    AnalysisReport,
    ReportAvailability,
    ShotAnalysis,
    StageAvailability,
)
from cine_analyzer.domain.spatial import SpatialValue
from cine_analyzer.domain.types import MetricStatus

__all__ = [
    "KIND_ESTIMATED",
    "KIND_INTERPRETED",
    "KIND_MEASURED",
    "KIND_UNAVAILABLE",
    "AvailabilityRow",
    "EvidenceChip",
    "PaletteBar",
    "ShotBar",
    "TensionSeries",
    "evidence_chips",
    "format_timecode",
    "is_terminal_status",
    "job_is_failed",
    "kind_for_metric_status",
    "kind_for_pillar",
    "lightness_markers",
    "palette_bars",
    "pillar_rows",
    "poll_delay_ms",
    "seek_seconds",
    "shot_bars",
    "shot_duration_histogram",
    "subject_schematic",
    "tension_series",
    "timeline_query",
]

KIND_MEASURED = "Measured"
KIND_ESTIMATED = "Estimated"
KIND_INTERPRETED = "Interpreted"
KIND_UNAVAILABLE = "Unavailable"

_PILLAR_KIND: dict[str, str] = {
    "shots": KIND_MEASURED,
    "chromatic": KIND_MEASURED,
    "spatial": KIND_ESTIMATED,
    "motion": KIND_MEASURED,
    "audio": KIND_MEASURED,
    "tension": KIND_MEASURED,
    "critic": KIND_INTERPRETED,
}


@dataclass(frozen=True, slots=True)
class PaletteBar:
    """One swatch sized by proportion for display."""

    rank: int
    hex_color: str
    proportion: float
    width_pct: float


@dataclass(frozen=True, slots=True)
class ShotBar:
    """One detected shot interval on the overview timeline."""

    shot_id: UUID
    index: int
    start_ms: int
    end_ms: int
    duration_ms: int
    label: str


@dataclass(frozen=True, slots=True)
class AvailabilityRow:
    """One pillar for the overview table."""

    name: str
    availability: str
    kind: str


@dataclass(frozen=True, slots=True)
class EvidenceChip:
    """One measured or estimated field shown beside optional interpretation."""

    label: str
    kind: str


@dataclass(frozen=True, slots=True)
class TensionSeries:
    """Bounded tension-proxy traces plus shot-boundary markers."""

    at_ms: tuple[int, ...]
    cut_activity: tuple[float, ...]
    audio_activity: tuple[float, ...]
    motion_activity: tuple[float, ...]
    combined_proxy: tuple[float, ...]
    shot_boundary_ms: tuple[int, ...]
    method_version: str
    warning: str


def format_timecode(ms: int) -> str:
    """Present integer milliseconds as ``[HH:]MM:SS.mmm``."""
    if ms < 0:
        message = "milliseconds must be >= 0"
        raise ValueError(message)
    hours, remainder = divmod(ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def seek_seconds(ms: int) -> int:
    """Whole-second offset for Streamlit ``st.video`` start_time."""
    if ms < 0:
        message = "milliseconds must be >= 0"
        raise ValueError(message)
    return ms // 1000


def poll_delay_ms(attempt: int, *, initial_ms: int = 250, cap_ms: int = 2000) -> int:
    """Exponential backoff for status polls. ``attempt`` is zero-based."""
    if attempt < 0:
        message = "attempt must be >= 0"
        raise ValueError(message)
    delay = initial_ms * (2**attempt)
    return min(int(delay), cap_ms)


def is_terminal_status(status: AnalysisStatusResponse) -> bool:
    """Stop polling when the analysis can no longer change."""
    return analysis_is_terminal(status.state)


def kind_for_pillar(name: str, availability: StageAvailability) -> str:
    """Measured / estimated / interpreted, or unavailable when the pillar did not complete."""
    if availability is not StageAvailability.COMPLETE:
        return KIND_UNAVAILABLE
    return _PILLAR_KIND.get(name, KIND_MEASURED)


def kind_for_metric_status(status: MetricStatus) -> str:
    """Envelope status for a single measurement."""
    if status is MetricStatus.OK:
        return KIND_MEASURED
    return KIND_UNAVAILABLE


def pillar_rows(availability: ReportAvailability) -> tuple[AvailabilityRow, ...]:
    """Stable pillar order for the overview table."""
    mapping = (
        ("shots", availability.shots),
        ("chromatic", availability.chromatic),
        ("spatial", availability.spatial),
        ("motion", availability.motion),
        ("audio", availability.audio),
        ("tension", availability.tension),
        ("critic", availability.critic),
    )
    return tuple(
        AvailabilityRow(name=name, availability=status.value, kind=kind_for_pillar(name, status))
        for name, status in mapping
    )


def evidence_chips(payload: CriticInput) -> tuple[EvidenceChip, ...]:
    """Compact chips from CriticInput. Palette hex and ratios are not model prose."""
    chips: list[EvidenceChip] = [
        EvidenceChip(label=f"{payload.editing.shot_count} shots", kind=KIND_MEASURED),
        EvidenceChip(label=f"ASL {payload.editing.asl_seconds}s", kind=KIND_MEASURED),
        EvidenceChip(label=f"median {payload.editing.median_seconds}s", kind=KIND_MEASURED),
        EvidenceChip(
            label=f"low-key estimate {payload.lighting.low_key_ratio}",
            kind=KIND_ESTIMATED,
        ),
        EvidenceChip(
            label=f"chromatic valid {payload.lighting.valid_shot_ratio}",
            kind=KIND_MEASURED,
        ),
        EvidenceChip(
            label=f"spatial valid {payload.composition.valid_shot_ratio}",
            kind=KIND_ESTIMATED,
        ),
    ]
    if payload.composition.median_thirds_proximity is not None:
        chips.append(
            EvidenceChip(
                label=f"thirds proximity {payload.composition.median_thirds_proximity}",
                kind=KIND_ESTIMATED,
            )
        )
    chips.extend(EvidenceChip(label=hex_color, kind=KIND_MEASURED) for hex_color in payload.palette)
    if payload.tension_proxy.audio_available:
        chips.append(EvidenceChip(label="audio present", kind=KIND_MEASURED))
    chips.extend(
        EvidenceChip(label=f"peak {peak}s", kind=KIND_MEASURED)
        for peak in payload.tension_proxy.peak_seconds
    )
    return tuple(chips)


def palette_bars(swatches: tuple[ColorSwatch, ...]) -> tuple[PaletteBar, ...]:
    """Widths follow recorded proportions. Hex is shown exactly as stored."""
    return tuple(
        PaletteBar(
            rank=swatch.rank,
            hex_color=swatch.rgb.hex,
            proportion=swatch.proportion,
            width_pct=round(swatch.proportion * 100.0, 4),
        )
        for swatch in swatches
    )


def shot_bars(report: AnalysisReport) -> tuple[ShotBar, ...]:
    """Detected shot intervals. These are not narrative scenes."""
    bars: list[ShotBar] = []
    for item in report.shots:
        duration = item.shot.time_range.duration_ms
        bars.append(
            ShotBar(
                shot_id=item.shot.shot_id,
                index=item.shot.index,
                start_ms=item.shot.time_range.start_ms,
                end_ms=item.shot.time_range.end_ms,
                duration_ms=duration,
                label=f"shot {item.shot.index} · {format_timecode(duration)}",
            )
        )
    return tuple(bars)


def shot_duration_histogram(report: AnalysisReport) -> tuple[int, ...]:
    """Per-shot durations in milliseconds for the ASL chart."""
    return tuple(item.shot.time_range.duration_ms for item in report.shots)


def lightness_markers(shot: ShotAnalysis) -> dict[str, float] | None:
    """Percentiles and ratios when chromatic measurement is present."""
    if shot.chromatic.status is not MetricStatus.OK or shot.chromatic.value is None:
        return None
    light = shot.chromatic.value.lightness
    return {
        "p10": light.p10_lstar,
        "p50": light.p50_lstar,
        "p90": light.p90_lstar,
        "mean": light.mean_lstar,
        "shadow_ratio": light.shadow_ratio,
        "highlight_ratio": light.highlight_ratio,
    }


def subject_schematic(value: SpatialValue) -> dict[str, float]:
    """Median coverage/height as a schematic box. Not a detector overlay on a frame."""
    width = min(1.0, max(0.05, value.subject_coverage_ratio_median**0.5))
    height = min(1.0, max(0.05, value.subject_height_ratio_median))
    x = (1.0 - width) / 2.0
    y = max(0.0, (1.0 - height) / 2.0)
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "coverage": value.subject_coverage_ratio_median,
        "subject_height": value.subject_height_ratio_median,
        "thirds_proximity": value.thirds_proximity_score,
        "center_proximity": value.center_proximity_score,
        "framing_confidence": value.framing_confidence,
    }


def timeline_query(duration_ms: int, *, max_points: int = 500) -> dict[str, int]:
    """Bounded window covering the whole clip."""
    end_ms = max(1, duration_ms)
    cap = min(max(1, max_points), DASHBOARD_TIMELINE_MAX_POINTS)
    return {"start_ms": 0, "end_ms": end_ms, "max_points": cap}


def tension_series(
    window: TimelineWindowResponse,
    report: AnalysisReport,
    *,
    method_version: str = "tension-v1",
) -> TensionSeries:
    """Component traces plus detected shot starts (not narrative scenes)."""
    points = window.points
    starts = tuple(item.shot.time_range.start_ms for item in report.shots)
    return TensionSeries(
        at_ms=tuple(point.at_ms for point in points),
        cut_activity=tuple(point.tension.cut_activity for point in points),
        audio_activity=tuple(point.tension.audio_activity for point in points),
        motion_activity=tuple(point.tension.motion_activity for point in points),
        combined_proxy=tuple(point.tension.combined_proxy for point in points),
        shot_boundary_ms=starts[1:],
        method_version=method_version,
        warning=(
            "Tension proxy is a configurable combination of cut, audio, and motion "
            "activity. It is not a measure of audience emotion."
        ),
    )


def job_is_failed(state: AnalysisState) -> bool:
    """True when the UI should freeze on an error panel."""
    return state is AnalysisState.FAILED
