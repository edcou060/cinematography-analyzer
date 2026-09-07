"""Product-contract vocabulary. No artistic-quality claims."""

from tests.factories import (
    make_provenance,
    make_shot_analysis,
    make_spatial_value,
    make_unavailable_spatial,
)

from cine_analyzer.dashboard.copy import (
    CAVEATS,
    PAGE_TITLE,
    SEEK_LIMITATION,
    SYNC_LIMITATION,
    caveats_markdown,
    critic_caption,
    empty_upload,
    evidence_chip_caption,
    failed_job,
    interpretation_label,
    lighting_caption,
    no_audio,
    no_subject,
    palette_caption,
    progress_caption,
    spatial_caption,
    state_caption,
    tension_caption,
)
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.spatial import SpatialMeasurement
from cine_analyzer.domain.types import MetricStatus


def test_caveats_deny_quality_and_narrative_claims() -> None:
    text = caveats_markdown()
    joined = " ".join(CAVEATS)
    assert "not narrative scenes" in joined
    assert "not a score of good composition" in joined
    assert "not lighting intent" in joined
    assert "PAGE_TITLE" not in text
    assert PAGE_TITLE
    assert SEEK_LIMITATION == SYNC_LIMITATION
    assert "whole seconds" in SYNC_LIMITATION
    assert "playhead" in SYNC_LIMITATION


def test_every_job_state_has_a_caption() -> None:
    for state in AnalysisState:
        caption = state_caption(state)
        assert caption
        assert "narrative scene" not in caption.lower()


def test_degraded_copy_covers_audio_subject_and_critic() -> None:
    assert "supported case" in no_audio(StageAvailability.UNAVAILABLE)
    assert "present" in no_audio(StageAvailability.COMPLETE)
    assert "No subject geometry" in no_subject(make_shot_analysis())
    present = make_shot_analysis().model_copy(
        update={
            "spatial": SpatialMeasurement(
                status=MetricStatus.OK,
                value=make_spatial_value(),
                method=make_provenance(),
            )
        }
    )
    assert "not a composition quality score" in no_subject(present)
    assert "disabled" in critic_caption(StageAvailability.NOT_REQUESTED)
    assert "unavailable" in critic_caption(StageAvailability.UNAVAILABLE)
    assert "optional prose" in critic_caption(StageAvailability.COMPLETE)
    assert make_unavailable_spatial().reason_code == "detector_not_installed"


def test_captions_name_methods_and_avoid_emotion_claims() -> None:
    assert "not a wall-clock estimate" in progress_caption()
    assert "schematic" in spatial_caption()
    assert "sRGB" in palette_caption()
    assert "not artistic intent" in lighting_caption()
    assert "not a measure of audience emotion" in tension_caption()
    assert "tension-v1" in tension_caption()
    assert "identifiers" in empty_upload()
    assert "could not be completed" in failed_job("the video was not found")
    assert interpretation_label() == "AI interpretation (optional)"
    assert "not model output" in evidence_chip_caption()
