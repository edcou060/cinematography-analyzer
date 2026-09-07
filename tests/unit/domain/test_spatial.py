"""Normalized boxes and subject observations."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.factories import make_spatial_value, make_unavailable_spatial

from cine_analyzer.domain.spatial import BoxNorm, FramingLabel, SpatialValue, SubjectObservation
from cine_analyzer.domain.types import MetricStatus


def test_a_degenerate_box_is_rejected() -> None:
    with pytest.raises(ValidationError, match="invalid normalized box"):
        BoxNorm(x_min=0.4, y_min=0.4, x_max=0.4, y_max=0.8)


def test_a_score_outside_unit_interval_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BoxNorm(x_min=-0.1, y_min=0.0, x_max=0.5, y_max=0.5)


def test_a_centroid_outside_the_box_is_rejected() -> None:
    box = BoxNorm(x_min=0.1, y_min=0.1, x_max=0.4, y_max=0.4)
    with pytest.raises(ValidationError, match="centroid_x"):
        SubjectObservation(
            track_id="t1",
            sample_id=uuid4(),
            class_name="person",
            detector_confidence=0.9,
            box=box,
            centroid_x=0.5,
            centroid_y=0.2,
        )
    with pytest.raises(ValidationError, match="centroid_y"):
        SubjectObservation(
            track_id="t1",
            sample_id=uuid4(),
            class_name="person",
            detector_confidence=0.9,
            box=box,
            centroid_x=0.2,
            centroid_y=0.9,
        )


def test_a_valid_observation_is_accepted() -> None:
    box = BoxNorm(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.8)
    observed = SubjectObservation(
        track_id="t1",
        sample_id=uuid4(),
        class_name="person",
        detector_confidence=0.9,
        box=box,
        centroid_x=0.3,
        centroid_y=0.5,
    )

    assert observed.centroid_x == 0.3


def test_framing_undetermined_is_a_label_not_a_missing_metric() -> None:
    value = make_spatial_value()
    labelled = value.model_copy(
        update={"framing": FramingLabel.UNDETERMINED, "framing_confidence": 0.0}
    )

    assert labelled.framing is FramingLabel.UNDETERMINED


def test_unavailable_spatial_has_a_reason_and_no_value() -> None:
    measurement = make_unavailable_spatial()

    assert measurement.status is MetricStatus.NOT_COMPUTED
    assert measurement.value is None
    assert measurement.reason_code == "detector_not_installed"


def test_spatial_value_forbids_unknown_fields() -> None:
    payload = make_spatial_value().model_dump(mode="json")
    payload["quality"] = 1.0
    with pytest.raises(ValidationError):
        SpatialValue.model_validate(payload)
