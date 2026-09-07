"""Hashed SpatialConfig fields change analysis identity (ADR-0013)."""

from cine_analyzer.domain.config import AnalysisConfig, FramingRules, PrimaryTrackWeights


def test_hashed_spatial_defaults_match_the_calibration_table() -> None:
    spatial = AnalysisConfig().spatial
    assert spatial.backend == "none"
    assert spatial.thirds_sigma == 0.18
    assert spatial.track_iou_min == 0.30
    assert spatial.primary_track_weights == PrimaryTrackWeights()
    assert spatial.framing_rules == FramingRules()
    assert spatial.framing_rules.version == "framing_rules_v1"


def test_a_framing_threshold_change_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["spatial"]["framing_rules"] = {
        **dumped["spatial"]["framing_rules"],
        "medium_height_max": 0.61,
    }
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()


def test_switching_the_backend_to_fake_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["spatial"]["backend"] = "fake"
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()
    assert changed.spatial.backend == "fake"
