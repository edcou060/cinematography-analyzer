"""Motion/audio/tension availability helpers and temporal mismatch."""

from datetime import UTC, datetime

import pytest
from tests.factories import (
    ANALYSIS_ID,
    make_ok_chromatic,
    make_ok_temporal,
    make_shot,
    make_shot_set,
    make_unavailable_spatial,
)
from tests.unit.application.fakes import FakeRepository, tiny_config, video_record_from_bytes

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.report import (
    assemble_report,
    audio_availability,
    motion_availability,
    tension_availability,
)
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import SCHEMA_VERSION, MetricStatus


def test_motion_availability_complete_partial_and_unavailable() -> None:
    missing = make_ok_temporal()
    present = make_ok_temporal().model_copy(
        update={
            "value": make_ok_temporal().value.model_copy(  # type: ignore[union-attr]
                update={"global_motion_magnitude": 0.1, "residual_motion_magnitude": 0.2}
            )
        }
    )
    assert motion_availability(()) is StageAvailability.UNAVAILABLE
    assert motion_availability((missing,)) is StageAvailability.UNAVAILABLE
    assert motion_availability((present,)) is StageAvailability.COMPLETE
    assert motion_availability((present, missing)) is StageAvailability.PARTIAL


def test_audio_availability_is_complete_only_when_ok() -> None:
    assert audio_availability(MetricStatus.OK) is StageAvailability.COMPLETE
    assert audio_availability(MetricStatus.NO_AUDIO) is StageAvailability.UNAVAILABLE
    assert audio_availability(MetricStatus.FAILED) is StageAvailability.UNAVAILABLE


def test_tension_availability_follows_points() -> None:
    empty = Timeline(schema_version=SCHEMA_VERSION, analysis_id=ANALYSIS_ID, points=())
    assert tension_availability(empty) is StageAvailability.UNAVAILABLE


def test_assemble_report_rejects_a_temporal_count_mismatch() -> None:
    video = video_record_from_bytes(b"clip")
    analysis = (
        CreateAnalysis(FakeRepository())
        .execute(video=video, config=tiny_config(), request_id="req-phase-07")
        .analysis
    )
    stamp = datetime(2026, 9, 6, tzinfo=UTC)
    with pytest.raises(ValueError, match="temporal measurements must match shot count"):
        assemble_report(
            video=video,
            analysis=analysis,
            config=tiny_config(),
            shot_set=make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=4000),)),
            chromatic=(make_ok_chromatic(),),
            spatial=(make_unavailable_spatial(),),
            temporal=(make_ok_temporal(), make_ok_temporal()),
            generated_at=stamp,
            started_at=stamp,
            completed_at=stamp,
        )
