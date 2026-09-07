"""Motion series alignment onto the tension hop."""

from tests.factories import ANALYSIS_ID, make_shot, make_shot_set

from cine_analyzer.application.motion import MotionSeriesPoint
from cine_analyzer.application.timeline import build_timeline, summarize_timeline
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.temporal import TensionComponents
from cine_analyzer.domain.timeline import Timeline, TimelinePoint
from cine_analyzer.domain.types import SCHEMA_VERSION


def test_motion_samples_in_a_window_are_averaged() -> None:
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=1000),))
    series = (
        MotionSeriesPoint(at_ms=100, shot_index=0, global_magnitude=0.8, residual_magnitude=0.1),
        MotionSeriesPoint(at_ms=200, shot_index=0, global_magnitude=0.2, residual_magnitude=0.1),
        MotionSeriesPoint(at_ms=800, shot_index=0, global_magnitude=0.0, residual_magnitude=0.9),
    )
    timeline = build_timeline(
        analysis_id=ANALYSIS_ID,
        shot_set=shot_set,
        config=AnalysisConfig(),
        motion_series=series,
        audio_windows=(),
        audio_available=False,
        motion_available=True,
        extra_warnings=("cut_like_flow_discontinuity",),
        audio_reason="no_audio_stream",
    )
    assert timeline.points[0].at_ms == 0
    assert timeline.points[1].at_ms == 500
    assert timeline.points[1].tension.motion_activity >= timeline.points[0].tension.motion_activity
    assert "cut_like_flow_discontinuity" in timeline.warnings


def test_nearest_motion_sample_is_used_when_the_window_is_empty() -> None:
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=1000),))
    series = (
        MotionSeriesPoint(at_ms=900, shot_index=0, global_magnitude=1.0, residual_magnitude=1.0),
    )
    timeline = build_timeline(
        analysis_id=ANALYSIS_ID,
        shot_set=shot_set,
        config=AnalysisConfig(),
        motion_series=series,
        audio_windows=(None,),
        audio_available=False,
        motion_available=True,
        extra_warnings=(),
        audio_reason=None,
    )
    assert len(timeline.points) == 2
    assert timeline.points[0].audio is None
    assert timeline.points[1].audio is None


def test_peak_plateau_keeps_the_first_local_maximum() -> None:
    def _point(at_ms: int, combined: float) -> TimelinePoint:
        return TimelinePoint(
            at_ms=at_ms,
            shot_index=0,
            tension=TensionComponents(
                cut_activity=combined,
                audio_activity=0.0,
                motion_activity=0.0,
                combined_proxy=combined,
            ),
        )

    timeline = Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(
            _point(0, 0.2),
            _point(500, 0.8),
            _point(1000, 0.8),
            _point(1500, 0.1),
        ),
    )
    peaks = summarize_timeline(timeline)["peaks"]
    times = [item["at_ms"] for item in peaks]
    assert 500 in times
    assert 1000 not in times


def test_duplicate_warnings_are_deduped_and_a_flat_proxy_still_has_a_peak() -> None:
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=1000),))
    timeline = build_timeline(
        analysis_id=ANALYSIS_ID,
        shot_set=shot_set,
        config=AnalysisConfig(),
        motion_series=(),
        audio_windows=(),
        audio_available=False,
        motion_available=False,
        extra_warnings=("no_audio_stream", "no_audio_stream"),
        audio_reason="no_audio_stream",
    )
    assert timeline.warnings.count("no_audio_stream") == 1
    peaks = summarize_timeline(timeline)["peaks"]
    assert len(peaks) == 1
    assert peaks[0]["combined_proxy"] == 0.0
