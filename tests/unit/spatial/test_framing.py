"""Framing estimates from the v1 calibration table. Labels are estimates."""

from uuid import UUID, uuid4

from tests.unit.spatial.helpers import box

from cine_analyzer.application.framing import (
    estimate_framing,
    framing_confidence,
    label_observation,
)
from cine_analyzer.domain.config import FramingRules
from cine_analyzer.domain.spatial import FramingLabel, SubjectObservation


def _obs(height: float, sample_id: UUID | None = None) -> SubjectObservation:
    top = max(0.0, min(1.0 - height, 0.1))
    return SubjectObservation(
        track_id="t0001",
        sample_id=sample_id or uuid4(),
        class_name="person",
        detector_confidence=0.9,
        box=box(0.3, top, 0.6, top + height),
        centroid_x=0.45,
        centroid_y=top + height / 2.0,
    )


def test_calibration_height_bands() -> None:
    rules = FramingRules()
    expected = (
        (0.10, FramingLabel.EXTREME_WIDE_ESTIMATE),
        (0.28, FramingLabel.WIDE_ESTIMATE),
        (0.50, FramingLabel.MEDIUM_ESTIMATE),
        (0.72, FramingLabel.CLOSE_UP_ESTIMATE),
        (0.92, FramingLabel.EXTREME_CLOSE_UP_ESTIMATE),
    )
    for height, label in expected:
        assert label_observation(_obs(height), rules) is label
        assert label is FramingLabel.UNDETERMINED or label.value.endswith("_ESTIMATE")


def test_exclusive_upper_thresholds() -> None:
    rules = FramingRules()
    assert label_observation(_obs(0.18), rules) is FramingLabel.WIDE_ESTIMATE
    assert label_observation(_obs(0.38), rules) is FramingLabel.MEDIUM_ESTIMATE
    assert label_observation(_obs(0.62), rules) is FramingLabel.CLOSE_UP_ESTIMATE
    assert label_observation(_obs(0.85), rules) is FramingLabel.EXTREME_CLOSE_UP_ESTIMATE


def test_truncation_forces_extreme_close_up() -> None:
    rules = FramingRules()
    cropped = SubjectObservation(
        track_id="t0001",
        sample_id=uuid4(),
        class_name="person",
        detector_confidence=0.9,
        box=box(0.2, 0.0, 0.7, 1.0),
        centroid_x=0.45,
        centroid_y=0.5,
    )
    assert label_observation(cropped, rules) is FramingLabel.EXTREME_CLOSE_UP_ESTIMATE


def test_disagreement_is_undetermined() -> None:
    rules = FramingRules()
    mixed = (_obs(0.28), _obs(0.72))
    assert estimate_framing(mixed, rules) is FramingLabel.UNDETERMINED
    confidence = framing_confidence(
        FramingLabel.UNDETERMINED, mixed, rules, track_coverage_ratio=1.0
    )
    assert 0.0 <= confidence <= 1.0


def test_majority_below_disagreement_fraction_keeps_the_winner() -> None:
    rules = FramingRules()
    members = (_obs(0.50), _obs(0.50), _obs(0.28))
    assert estimate_framing(members, rules) is FramingLabel.MEDIUM_ESTIMATE
    confidence = framing_confidence(FramingLabel.MEDIUM_ESTIMATE, members, rules, 1.0)
    assert 0.0 < confidence <= 1.0


def test_empty_observations_are_undetermined_with_zero_confidence() -> None:
    rules = FramingRules()
    assert estimate_framing((), rules) is FramingLabel.UNDETERMINED
    assert framing_confidence(FramingLabel.UNDETERMINED, (), rules, 0.0) == 0.0


def test_agreed_medium_has_heuristic_confidence() -> None:
    rules = FramingRules()
    members = (_obs(0.50), _obs(0.52))
    label = estimate_framing(members, rules)
    assert label is FramingLabel.MEDIUM_ESTIMATE
    confidence = framing_confidence(label, members, rules, 1.0)
    assert 0.0 < confidence <= 1.0
