"""CriticInput excludes filenames/paths and rounds display seconds."""

import json

import pytest
from pydantic import ValidationError
from tests.factories import (
    make_chromatic_value,
    make_provenance,
    make_report,
    make_shot,
    make_shot_analysis,
    make_spatial_value,
    make_swatch,
    make_unavailable_spatial,
    make_video,
)

from cine_analyzer.domain.chromatics import ChromaticMeasurement, LightingKeyLabel
from cine_analyzer.domain.critic import CriticInput, CriticOutput
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.spatial import SpatialMeasurement
from cine_analyzer.domain.types import MetricStatus


def test_from_report_omits_filename_path_and_ids() -> None:
    report = make_report(video=make_video(original_filename="clip.mp4"))
    payload = CriticInput.from_report(report)
    dumped = json.dumps(payload.model_dump(mode="json"))
    assert "clip.mp4" not in dumped
    assert "original_filename" not in dumped
    assert "/Users/" not in dumped
    assert str(report.analysis_id) not in dumped
    assert str(report.video.video_id) not in dumped
    assert payload.editing.shot_count == 1
    assert payload.editing.asl_seconds == 4.0
    assert payload.palette == ("#102030",)
    assert payload.composition.median_thirds_proximity is None
    assert payload.tension_proxy.peak_seconds == ()
    assert payload.tension_proxy.audio_available is False


def test_from_report_handles_missing_spatial_audio_and_low_key() -> None:
    chromatic = ChromaticMeasurement(
        status=MetricStatus.OK,
        value=make_chromatic_value().model_copy(
            update={
                "lighting_key": LightingKeyLabel.LOW_KEY_ESTIMATE,
                "palette": (make_swatch(rank=1, proportion=1.0, red=23, green=33, blue=43),),
            }
        ),
        method=make_provenance(),
    )
    spatial = SpatialMeasurement(
        status=MetricStatus.OK,
        value=make_spatial_value(),
        method=make_provenance(),
    )
    missing = make_shot_analysis(make_shot(index=1, start_ms=4000, end_ms=8000)).model_copy(
        update={
            "chromatic": ChromaticMeasurement(
                status=MetricStatus.NOT_COMPUTED,
                value=None,
                reason_code="insufficient_data",
                method=make_provenance(),
            ),
            "spatial": make_unavailable_spatial(),
        }
    )
    first = make_shot_analysis().model_copy(update={"chromatic": chromatic, "spatial": spatial})
    report = make_report(
        video=make_video(has_audio=True, audio_codec="aac"),
        availability=make_report().availability.model_copy(
            update={
                "audio": StageAvailability.COMPLETE,
                "spatial": StageAvailability.PARTIAL,
            }
        ),
        summary=make_report().summary.model_copy(
            update={
                "shot_count": 2,
                "average_shot_length_ms": 4000.0,
                "median_shot_length_ms": 4000.0,
            }
        ),
        shots=(first, missing),
    )
    payload = CriticInput.from_report(report, peak_ms=(12000, 37500, 1))
    assert payload.lighting.low_key_ratio == 1.0
    assert payload.lighting.valid_shot_ratio == 0.5
    assert payload.composition.valid_shot_ratio == 0.5
    assert payload.composition.median_thirds_proximity == 0.5
    assert payload.tension_proxy.audio_available is True
    assert payload.tension_proxy.peak_seconds == (12.0, 37.5, 0.0)


def test_from_report_zero_chromatic_coverage() -> None:
    shot = make_shot_analysis().model_copy(
        update={
            "chromatic": ChromaticMeasurement(
                status=MetricStatus.FAILED,
                value=None,
                reason_code="failed",
                method=make_provenance(),
            )
        }
    )
    report = make_report(shots=(shot,))
    payload = CriticInput.from_report(report)
    assert payload.lighting.low_key_ratio == 0.0
    assert payload.lighting.valid_shot_ratio == 0.0
    assert payload.palette == ()


def test_critic_output_rejects_empty_and_overlong_sentences() -> None:
    with pytest.raises(ValidationError, match="empty"):
        CriticOutput(sentences=("   ",))
    with pytest.raises(ValidationError, match="length"):
        CriticOutput(sentences=("x" * 201,))
    assert CriticOutput(sentences=("One.", "Two.")).as_text() == "One. Two."


def test_unknown_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        CriticInput.model_validate(
            {
                "schema_version": "1.0",
                "editing": {"shot_count": 1, "asl_seconds": 1.0, "median_seconds": 1.0},
                "lighting": {"low_key_ratio": 0.0, "valid_shot_ratio": 1.0},
                "palette": [],
                "composition": {"valid_shot_ratio": 0.0},
                "tension_proxy": {"peak_seconds": [], "audio_available": False},
                "original_filename": "secret.mp4",
            }
        )
