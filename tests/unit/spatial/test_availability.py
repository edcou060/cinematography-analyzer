"""Spatial pillar availability and report assembly mismatches."""

from datetime import UTC, datetime

import pytest
from tests.factories import (
    make_ok_chromatic,
    make_provenance,
    make_shot,
    make_shot_set,
    make_spatial_value,
    make_unavailable_spatial,
)
from tests.unit.application.fakes import FakeRepository, tiny_config, video_record_from_bytes

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.report import assemble_report, spatial_availability
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.spatial import SpatialMeasurement
from cine_analyzer.domain.types import MetricStatus


def _ok() -> SpatialMeasurement:
    return SpatialMeasurement(
        status=MetricStatus.OK,
        value=make_spatial_value(),
        method=make_provenance(method="spatial.fake"),
    )


def _none() -> SpatialMeasurement:
    return make_unavailable_spatial()


def _no_subject() -> SpatialMeasurement:
    return SpatialMeasurement(
        status=MetricStatus.NO_SUBJECT,
        value=None,
        reason_code="spatial_no_subject",
        method=make_provenance(method="spatial.fake"),
    )


def test_spatial_availability_complete_partial_and_unavailable() -> None:
    assert spatial_availability(()) is StageAvailability.UNAVAILABLE
    assert spatial_availability((_none(), _none())) is StageAvailability.UNAVAILABLE
    assert spatial_availability((_ok(), _ok())) is StageAvailability.COMPLETE
    assert spatial_availability((_ok(), _no_subject())) is StageAvailability.COMPLETE
    assert spatial_availability((_no_subject(),)) is StageAvailability.COMPLETE
    assert spatial_availability((_ok(), _none())) is StageAvailability.PARTIAL
    missing = SpatialMeasurement(
        status=MetricStatus.INSUFFICIENT_DATA,
        value=None,
        reason_code="spatial_no_decoded_samples",
        method=make_provenance(),
    )
    assert spatial_availability((missing,)) is StageAvailability.UNAVAILABLE
    assert spatial_availability((_ok(), missing)) is StageAvailability.PARTIAL


def test_assemble_report_rejects_a_spatial_count_mismatch() -> None:
    video = video_record_from_bytes(b"clip")
    analysis = (
        CreateAnalysis(FakeRepository())
        .execute(video=video, config=tiny_config(), request_id="req-phase-03")
        .analysis
    )
    stamp = datetime(2026, 9, 6, tzinfo=UTC)
    with pytest.raises(ValueError, match="spatial measurements must match shot count"):
        assemble_report(
            video=video,
            analysis=analysis,
            config=tiny_config(),
            shot_set=make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=4000),)),
            chromatic=(make_ok_chromatic(),),
            spatial=(_none(), _none()),
            generated_at=stamp,
            started_at=stamp,
            completed_at=stamp,
        )
