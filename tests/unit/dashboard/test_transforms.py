"""Millisecond presentation helpers and bounded timeline queries."""

import pytest
from tests.factories import (
    ANALYSIS_ID,
    SAMPLE_ID,
    make_availability,
    make_ok_chromatic,
    make_provenance,
    make_report,
    make_shot,
    make_shot_analysis,
    make_spatial_value,
    make_swatch,
    make_unavailable_spatial,
)
from tests.unit.domain.test_timeline import _point

from cine_analyzer.api.schemas import TimelineWindowResponse
from cine_analyzer.dashboard.client import DASHBOARD_TIMELINE_MAX_POINTS
from cine_analyzer.dashboard.transforms import (
    KIND_ESTIMATED,
    KIND_INTERPRETED,
    KIND_MEASURED,
    KIND_UNAVAILABLE,
    evidence_chips,
    format_timecode,
    is_terminal_status,
    job_is_failed,
    kind_for_metric_status,
    kind_for_pillar,
    lightness_markers,
    palette_bars,
    pillar_rows,
    poll_delay_ms,
    seek_seconds,
    shot_bars,
    shot_duration_histogram,
    subject_schematic,
    tension_series,
    timeline_query,
)
from cine_analyzer.domain.chromatics import ChromaticMeasurement, ChromaticValue
from cine_analyzer.domain.critic import CriticInput
from cine_analyzer.domain.jobs import AnalysisState, AnalysisStatusResponse
from cine_analyzer.domain.report import StageAvailability, VideoSummary
from cine_analyzer.domain.spatial import SpatialMeasurement
from cine_analyzer.domain.types import MetricStatus


def _status(state: AnalysisState) -> AnalysisStatusResponse:
    return AnalysisStatusResponse(
        analysis_id=ANALYSIS_ID,
        state=state,
        progress=1.0 if state in {AnalysisState.SUCCEEDED, AnalysisState.PARTIAL} else 0.4,
        completed_stages=(),
        active_stages=(),
        unavailable_stages=(),
    )


def test_timecode_formats_minutes_and_hours() -> None:
    assert format_timecode(0) == "00:00.000"
    assert format_timecode(61_001) == "01:01.001"
    assert format_timecode(3_600_000) == "01:00:00.000"
    with pytest.raises(ValueError, match="milliseconds"):
        format_timecode(-1)


def test_seek_truncates_to_whole_seconds() -> None:
    assert seek_seconds(0) == 0
    assert seek_seconds(1999) == 1
    with pytest.raises(ValueError, match="milliseconds"):
        seek_seconds(-1)


def test_poll_backoff_caps() -> None:
    assert poll_delay_ms(0) == 250
    assert poll_delay_ms(10) == 2000
    with pytest.raises(ValueError, match="attempt"):
        poll_delay_ms(-1)


def test_terminal_and_failed_states() -> None:
    assert is_terminal_status(_status(AnalysisState.SUCCEEDED)) is True
    assert is_terminal_status(_status(AnalysisState.RUNNING)) is False
    assert job_is_failed(AnalysisState.FAILED) is True
    assert job_is_failed(AnalysisState.CANCELED) is False


def test_kinds_distinguish_unavailable_pillars() -> None:
    assert kind_for_pillar("spatial", StageAvailability.COMPLETE) == KIND_ESTIMATED
    assert kind_for_pillar("critic", StageAvailability.COMPLETE) == KIND_INTERPRETED
    assert kind_for_pillar("shots", StageAvailability.COMPLETE) == KIND_MEASURED
    assert kind_for_pillar("audio", StageAvailability.UNAVAILABLE) == KIND_UNAVAILABLE
    assert kind_for_pillar("unknown", StageAvailability.COMPLETE) == KIND_MEASURED
    assert kind_for_metric_status(MetricStatus.OK) == KIND_MEASURED
    assert kind_for_metric_status(MetricStatus.NO_SUBJECT) == KIND_UNAVAILABLE


def test_pillar_rows_follow_a_stable_order() -> None:
    rows = pillar_rows(make_availability())
    assert [row.name for row in rows] == [
        "shots",
        "chromatic",
        "spatial",
        "motion",
        "audio",
        "tension",
        "critic",
    ]
    assert rows[2].kind == KIND_UNAVAILABLE
    assert rows[6].kind == KIND_UNAVAILABLE


def test_palette_widths_follow_proportions() -> None:
    bars = palette_bars(
        (
            make_swatch(rank=1, proportion=0.75, red=16, green=32, blue=48),
            make_swatch(rank=2, proportion=0.25, red=200, green=10, blue=10),
        )
    )
    assert bars[0].hex_color == "#102030"
    assert bars[0].width_pct == 75.0
    assert bars[1].width_pct == 25.0
    assert palette_bars(()) == ()


def test_shot_bars_and_histogram_are_not_narrative_scenes() -> None:
    first = make_shot(index=0, start_ms=0, end_ms=1500)
    second = make_shot(index=1, start_ms=1500, end_ms=4000)
    report = make_report(
        shots=(make_shot_analysis(first), make_shot_analysis(second)),
        summary=VideoSummary(
            shot_count=2,
            average_shot_length_ms=2000.0,
            median_shot_length_ms=2000.0,
            shots_per_minute=30.0,
        ),
    )
    bars = shot_bars(report)
    assert bars[0].label.startswith("shot 0")
    assert "scene" not in bars[0].label.lower()
    assert shot_duration_histogram(report) == (1500, 2500)


def test_lightness_markers_require_an_ok_chromatic_value() -> None:
    ok = make_shot_analysis()
    assert lightness_markers(ok) == {
        "p10": 20.0,
        "p50": 40.0,
        "p90": 60.0,
        "mean": 40.0,
        "shadow_ratio": 0.2,
        "highlight_ratio": 0.1,
    }
    missing = make_shot_analysis().model_copy(
        update={
            "chromatic": ChromaticMeasurement(
                status=MetricStatus.FAILED,
                value=None,
                reason_code="chromatic_failed",
                method=make_provenance(),
            )
        }
    )
    assert lightness_markers(missing) is None


def test_schematic_box_clamps_extreme_coverage() -> None:
    tiny = make_spatial_value().model_copy(
        update={"subject_coverage_ratio_median": 0.0, "subject_height_ratio_median": 0.0}
    )
    box = subject_schematic(tiny)
    assert box["width"] == 0.05
    assert box["height"] == 0.05
    wide = make_spatial_value().model_copy(
        update={"subject_coverage_ratio_median": 1.0, "subject_height_ratio_median": 1.0}
    )
    full = subject_schematic(wide)
    assert full["width"] == 1.0
    assert full["x"] == 0.0


def test_timeline_query_is_bounded_and_covers_the_clip() -> None:
    assert timeline_query(0) == {"start_ms": 0, "end_ms": 1, "max_points": 500}
    query = timeline_query(12_000, max_points=9_000)
    assert query["end_ms"] == 12_000
    assert query["max_points"] == DASHBOARD_TIMELINE_MAX_POINTS
    assert timeline_query(1000, max_points=0)["max_points"] == 1


def test_tension_series_marks_detected_shot_starts_not_the_clip_origin() -> None:
    first = make_shot(index=0, start_ms=0, end_ms=2000)
    second = make_shot(index=1, start_ms=2000, end_ms=4000)
    report = make_report(
        shots=(make_shot_analysis(first), make_shot_analysis(second)),
        summary=VideoSummary(
            shot_count=2,
            average_shot_length_ms=2000.0,
            median_shot_length_ms=2000.0,
            shots_per_minute=30.0,
        ),
    )
    window = TimelineWindowResponse(
        analysis_id=ANALYSIS_ID,
        start_ms=0,
        end_ms=4000,
        max_points=10,
        points=(_point(0), _point(1000), _point(2000)),
    )
    series = tension_series(window, report)
    assert series.shot_boundary_ms == (2000,)
    assert "not a measure of audience emotion" in series.warning
    assert series.method_version == "tension-v1"
    assert len(series.combined_proxy) == 3


def test_ok_spatial_shot_keeps_evidence_sample_ids() -> None:
    chromatic = make_ok_chromatic().model_copy(update={"evidence_sample_ids": (SAMPLE_ID,)})
    spatial = SpatialMeasurement(
        status=MetricStatus.OK,
        value=make_spatial_value(),
        method=make_provenance(),
    )
    shot = make_shot_analysis().model_copy(update={"chromatic": chromatic, "spatial": spatial})
    assert shot.chromatic.evidence_sample_ids == (SAMPLE_ID,)
    assert make_unavailable_spatial().value is None
    value = chromatic.value
    assert isinstance(value, ChromaticValue)
    assert palette_bars(value.palette)[0].rank == 1


def test_evidence_chips_come_from_report_not_the_model() -> None:
    chips = evidence_chips(CriticInput.from_report(make_report()))
    labels = " ".join(chip.label for chip in chips)
    assert "1 shots" in labels
    assert "#102030" in labels
    assert KIND_MEASURED in {chip.kind for chip in chips}
    peaked = evidence_chips(
        CriticInput.from_report(make_report(), peak_ms=(12000,)).model_copy(
            update={
                "composition": CriticInput.from_report(make_report()).composition.model_copy(
                    update={"median_thirds_proximity": 0.5}
                ),
                "tension_proxy": CriticInput.from_report(make_report()).tension_proxy.model_copy(
                    update={"audio_available": True, "peak_seconds": (12.0,)}
                ),
            }
        )
    )
    peaked_labels = " ".join(chip.label for chip in peaked)
    assert "thirds proximity 0.5" in peaked_labels
    assert "audio present" in peaked_labels
    assert "peak 12.0s" in peaked_labels
