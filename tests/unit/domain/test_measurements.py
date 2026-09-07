"""Measurement envelope: a value or a named reason, never an unexplained null."""

import pytest
from pydantic import ValidationError
from tests.factories import make_provenance

from cine_analyzer.domain.measurements import Measurement
from cine_analyzer.domain.types import MetricStatus


def test_ok_requires_a_value() -> None:
    with pytest.raises(ValidationError, match="OK measurement requires a value"):
        Measurement[int](
            status=MetricStatus.OK,
            value=None,
            method=make_provenance(),
        )


def test_ok_rejects_a_reason_code() -> None:
    with pytest.raises(ValidationError, match="must not carry a reason_code"):
        Measurement[int](
            status=MetricStatus.OK,
            value=3,
            reason_code="unused",
            method=make_provenance(),
        )


def test_non_ok_rejects_a_value() -> None:
    with pytest.raises(ValidationError, match="must not contain a value"):
        Measurement[int](
            status=MetricStatus.NO_AUDIO,
            value=0,
            reason_code="no_audio_stream",
            method=make_provenance(),
        )


def test_non_ok_requires_a_reason_code() -> None:
    with pytest.raises(ValidationError, match="requires a reason_code"):
        Measurement[int](
            status=MetricStatus.FAILED,
            value=None,
            method=make_provenance(),
        )


def test_an_absent_metric_carries_status_and_reason() -> None:
    measurement = Measurement[int](
        status=MetricStatus.NO_SUBJECT,
        value=None,
        reason_code="detector_not_installed",
        method=make_provenance(),
    )

    assert measurement.value is None
    assert measurement.reason_code == "detector_not_installed"


def test_ok_round_trips() -> None:
    measurement = Measurement[int](
        status=MetricStatus.OK,
        value=7,
        confidence=0.5,
        method=make_provenance(),
    )

    assert Measurement[int].model_validate_json(measurement.model_dump_json()) == measurement
