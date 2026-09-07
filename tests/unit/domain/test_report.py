"""Report consistency: shot counts, indices, and honest audio availability."""

import pytest
from pydantic import ValidationError
from tests.factories import DIGEST, make_availability, make_report, make_shot, make_shot_analysis

from cine_analyzer.domain.report import Critique, StageAvailability, VideoSummary
from cine_analyzer.domain.types import SCHEMA_VERSION, MetricStatus


def test_shot_count_must_match_the_shot_list() -> None:
    with pytest.raises(ValidationError, match="shot_count"):
        make_report(
            summary=VideoSummary(
                shot_count=2,
                average_shot_length_ms=2000.0,
                median_shot_length_ms=2000.0,
                shots_per_minute=30.0,
            )
        )


def test_report_shot_indices_must_be_contiguous() -> None:
    with pytest.raises(ValidationError, match="contiguous from zero"):
        make_report(shots=(make_shot_analysis(make_shot(index=1, start_ms=0, end_ms=4000)),))


def test_audio_cannot_be_complete_without_an_audio_stream() -> None:
    with pytest.raises(ValidationError, match="audio cannot be COMPLETE"):
        make_report(availability=make_availability(audio=StageAvailability.COMPLETE))


def test_an_unsupported_report_schema_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        make_report(schema_version="2.0")


def test_ok_critique_requires_text() -> None:
    with pytest.raises(ValidationError, match="OK critique requires text"):
        Critique(status=MetricStatus.OK, text=None, input_report_sha256=DIGEST)
    with pytest.raises(ValidationError, match="OK critique requires text"):
        Critique(status=MetricStatus.OK, text="", input_report_sha256=DIGEST)


def test_ok_critique_with_text_is_accepted() -> None:
    critique = Critique(
        status=MetricStatus.OK,
        text="Measured, not judged.",
        input_report_sha256=DIGEST,
    )

    assert critique.text is not None


def test_non_ok_critique_rejects_text() -> None:
    with pytest.raises(ValidationError, match="must not contain text"):
        Critique(status=MetricStatus.FAILED, text="nope")


def test_failed_critique_without_text_is_accepted() -> None:
    critique = Critique(status=MetricStatus.FAILED, text=None)

    assert critique.text is None


def test_a_valid_report_round_trips() -> None:
    report = make_report()

    assert report.schema_version == SCHEMA_VERSION
    restored = type(report).model_validate_json(report.model_dump_json())
    assert restored == report
