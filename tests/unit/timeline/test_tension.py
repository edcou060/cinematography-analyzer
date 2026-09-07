"""Tension proxy: robust norm, cut activity, renormalization, monotonicity."""

import math

from tests.factories import ANALYSIS_ID, make_shot, make_shot_set

from cine_analyzer.application.cut_activity import cut_activity, internal_boundary_ms
from cine_analyzer.application.normalize import clip01, robust_normalize
from cine_analyzer.application.tension import (
    AUDIO_UNAVAILABLE_WARNING,
    MOTION_UNAVAILABLE_WARNING,
    combine_tension,
    effective_weights,
)
from cine_analyzer.application.timeline import build_timeline, summarize_timeline
from cine_analyzer.domain.config import AnalysisConfig, TensionWeights
from cine_analyzer.domain.temporal import AudioWindowValue
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import SCHEMA_VERSION


def test_constant_series_normalizes_to_zero() -> None:
    values = robust_normalize(
        (4.0, 4.0, 4.0, 4.0),
        percentile_low=10.0,
        percentile_high=90.0,
        epsilon=1e-6,
    )
    assert values == (0.0, 0.0, 0.0, 0.0)


def test_empty_series_normalizes_to_empty() -> None:
    assert robust_normalize((), percentile_low=10.0, percentile_high=90.0, epsilon=1e-6) == ()


def test_clip01_maps_non_finite_to_zero() -> None:
    assert clip01(float("nan")) == 0.0
    assert clip01(float("inf")) == 0.0
    assert clip01(-2.0) == 0.0
    assert clip01(2.0) == 1.0
    assert clip01(0.4) == 0.4


def test_cut_activity_peaks_at_the_boundary() -> None:
    config = AnalysisConfig().tension
    boundaries = internal_boundary_ms((0, 2000))
    assert boundaries == (2000,)
    peak = cut_activity(2000, boundaries, config)
    nearby = cut_activity(0, boundaries, config)
    assert peak > nearby
    assert 0.0 <= peak <= 1.0
    assert cut_activity(0, (), config) == 0.0


def test_missing_audio_renormalizes_remaining_weights() -> None:
    configured = TensionWeights(cut_activity=0.35, audio_activity=0.30, motion=0.35)
    weights, warnings = effective_weights(configured, audio_available=False, motion_available=True)
    assert math.isclose(weights.cut_activity + weights.motion, 1.0)
    assert weights.audio_activity == 0.0
    assert AUDIO_UNAVAILABLE_WARNING in warnings
    low = combine_tension(
        cut_activity=0.2, audio_activity=0.0, motion_activity=0.1, weights=weights
    )
    high = combine_tension(
        cut_activity=0.8, audio_activity=0.0, motion_activity=0.1, weights=weights
    )
    assert high.combined_proxy >= low.combined_proxy
    assert 0.0 <= low.cut_activity <= 1.0
    assert 0.0 <= low.audio_activity <= 1.0
    assert 0.0 <= low.motion_activity <= 1.0
    assert 0.0 <= low.combined_proxy <= 1.0


def test_all_remaining_weights_zero_falls_back_to_cut() -> None:
    configured = TensionWeights(cut_activity=0.0, audio_activity=0.5, motion=0.5)
    weights, warnings = effective_weights(configured, audio_available=False, motion_available=False)
    assert weights.cut_activity == 1.0
    assert MOTION_UNAVAILABLE_WARNING in warnings
    assert AUDIO_UNAVAILABLE_WARNING in warnings


def test_build_timeline_stores_every_component_when_audio_is_missing() -> None:
    shot_set = make_shot_set(
        shots=(
            make_shot(index=0, start_ms=0, end_ms=2000),
            make_shot(index=1, start_ms=2000, end_ms=4000),
        )
    )
    starts = tuple(range(0, 4000, 500))
    timeline = build_timeline(
        analysis_id=ANALYSIS_ID,
        shot_set=shot_set,
        config=AnalysisConfig(),
        motion_series=(),
        audio_windows=tuple(None for _ in starts),
        audio_available=False,
        motion_available=False,
        extra_warnings=(),
        audio_reason="no_audio_stream",
    )
    assert timeline.warnings[0] == "no_audio_stream"
    assert all(point.audio is None for point in timeline.points)
    assert all(point.tension.audio_activity == 0.0 for point in timeline.points)
    cut_at_boundary = next(point for point in timeline.points if point.at_ms == 2000)
    assert cut_at_boundary.tension.cut_activity > 0.0
    summary = summarize_timeline(timeline)
    assert summary["label"] == "tension proxy"
    assert "emotion" not in str(summary).lower()
    assert summary["peaks"]
    assert {"cut_activity", "audio_activity", "motion_activity", "combined_proxy"} <= set(
        summary["peaks"][0]
    )


def test_summarize_empty_timeline_has_no_peaks() -> None:
    timeline = Timeline(schema_version=SCHEMA_VERSION, analysis_id=ANALYSIS_ID, points=())
    assert summarize_timeline(timeline)["peaks"] == []
    assert summarize_timeline(timeline)["point_count"] == 0


def test_audio_windows_are_aligned_to_the_same_starts() -> None:
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=1000),))
    window = AudioWindowValue(
        rms_dbfs=-6.0,
        onset_strength=2.0,
        spectral_flux=2.0,
        loudness_lufs_short_term=None,
    )
    quiet = AudioWindowValue(
        rms_dbfs=-60.0,
        onset_strength=0.0,
        spectral_flux=0.0,
        loudness_lufs_short_term=None,
    )
    timeline = build_timeline(
        analysis_id=ANALYSIS_ID,
        shot_set=shot_set,
        config=AnalysisConfig(),
        motion_series=(),
        audio_windows=(quiet, window),
        audio_available=True,
        motion_available=False,
        extra_warnings=(),
        audio_reason=None,
    )
    assert timeline.points[0].audio is quiet
    assert timeline.points[1].audio is window
    assert timeline.points[1].tension.audio_activity >= timeline.points[0].tension.audio_activity
