"""Canonical config hashing: key order is irrelevant; semantics are not."""

import pytest
from pydantic import ValidationError

from cine_analyzer.domain.config import (
    AnalysisConfig,
    FramingRules,
    PrimaryTrackWeights,
    TensionWeights,
    canonical_hash,
)
from cine_analyzer.domain.types import SCHEMA_VERSION


def test_default_config_hash_is_stable_across_construction_order() -> None:
    left = AnalysisConfig()
    right = AnalysisConfig.model_validate(left.model_dump(mode="json"))

    assert left.hash() == right.hash() == canonical_hash(left)


def test_reordered_nested_keys_do_not_change_the_hash() -> None:
    dumped = AnalysisConfig().model_dump(mode="json")
    dumped["limits"] = {
        "max_height": dumped["limits"]["max_height"],
        "max_width": dumped["limits"]["max_width"],
        "max_duration_ms": dumped["limits"]["max_duration_ms"],
        "max_upload_bytes": dumped["limits"]["max_upload_bytes"],
    }

    assert canonical_hash(AnalysisConfig.model_validate(dumped)) == AnalysisConfig().hash()


def test_a_semantic_change_changes_the_hash() -> None:
    baseline = AnalysisConfig().hash()
    changed = AnalysisConfig.model_validate(
        {**AnalysisConfig().model_dump(mode="json"), "pipeline_version": "0.1.1"}
    )

    assert changed.hash() != baseline


def test_enabling_the_critic_changes_the_hash() -> None:
    enabled = AnalysisConfig.model_validate(
        {
            **AnalysisConfig().model_dump(mode="json"),
            "critic": {"enabled": True},
        }
    )

    assert enabled.hash() != AnalysisConfig().hash()
    assert enabled.critic.enabled is True


def test_tension_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        TensionWeights(cut_activity=0.5, audio_activity=0.5, motion=0.5)


def test_an_unsupported_config_schema_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        AnalysisConfig(schema_version="0.9")


def test_default_spatial_backend_is_none() -> None:
    """Base install: no detector. The gated adapter is not the hashed default."""
    spatial = AnalysisConfig().spatial
    assert spatial.backend == "none"
    assert spatial.checkpoint is None
    assert spatial.thirds_sigma == 0.18
    assert spatial.track_iou_min == 0.30
    assert spatial.primary_track_weights.coverage == 0.45
    assert spatial.framing_rules.version == "framing_rules_v1"
    assert AnalysisConfig().schema_version == SCHEMA_VERSION
    assert AnalysisConfig().critic.enabled is False


def test_primary_track_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        PrimaryTrackWeights(coverage=0.5, median_area=0.5, median_confidence=0.5)


def test_framing_height_thresholds_must_increase() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        FramingRules(
            extreme_wide_height_max=0.50,
            wide_height_max=0.40,
            medium_height_max=0.62,
            close_up_height_max=0.85,
        )


def test_hashed_shot_detector_fields_have_documented_defaults() -> None:
    shots = AnalysisConfig().shots
    assert shots.working_width == 320
    assert shots.threshold == 3.0
    assert shots.min_content_val == 15.0
    assert shots.debug is False


def test_a_detector_threshold_change_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["shots"] = {**dumped["shots"], "threshold": 4.0}
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()


def test_hashed_chromatic_fields_have_documented_defaults() -> None:
    chromatic = AnalysisConfig().chromatic
    assert chromatic.working_max_side == 640
    assert chromatic.kmeans_n_init == 3
    assert chromatic.kmeans_batch_size == 1024
    assert chromatic.delta_e_merge == 3.0
    assert chromatic.letterbox_lstar_max == 8.0
    assert chromatic.min_usable_pixel_ratio == 0.05
    assert chromatic.min_swatch_proportion == 0.02
    assert chromatic.lighting_key_rules.low_median_lstar == 40.0


def test_a_lighting_key_threshold_change_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["chromatic"]["lighting_key_rules"] = {
        **dumped["chromatic"]["lighting_key_rules"],
        "low_median_lstar": 35.0,
    }
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()


def test_a_framing_threshold_change_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["spatial"]["framing_rules"] = {
        **dumped["spatial"]["framing_rules"],
        "medium_height_max": 0.61,
    }
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()


def test_hashed_motion_fields_have_documented_defaults() -> None:
    motion = AnalysisConfig().motion
    assert motion.working_max_side == 320
    assert motion.discontinuity_diag_per_s == 1.5
    assert motion.farneback.winsize == 15
    audio = AnalysisConfig().audio
    assert audio.window_ms == 1000
    tension = AnalysisConfig().tension
    assert tension.hop_ms == 500
    assert tension.cut_sigma_ms == 750
    assert tension.cut_reference == 3.0
    assert tension.percentile_low == 10.0
    assert tension.epsilon == 1e-6


def test_a_motion_resolution_change_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["motion"]["working_max_side"] = 160
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()


def test_an_audio_window_change_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["audio"]["window_ms"] = 750
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()


def test_a_tension_kernel_change_changes_the_hash() -> None:
    baseline = AnalysisConfig()
    dumped = baseline.model_dump(mode="json")
    dumped["tension"]["cut_reference"] = 2.5
    changed = AnalysisConfig.model_validate(dumped)
    assert changed.hash() != baseline.hash()
