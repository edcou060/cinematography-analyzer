"""Box IoU, thirds proximity, and center proximity."""

import math

from tests.unit.spatial.helpers import box

from cine_analyzer.application.spatial_geometry import (
    box_area,
    box_centroid,
    box_height,
    box_iou,
    center_proximity,
    is_vertically_truncated,
    proximity_score,
    thirds_proximity,
)


def test_centroid_and_area_and_height() -> None:
    subject = box(0.2, 0.1, 0.6, 0.5)
    assert box_centroid(subject) == (0.4, 0.3)
    assert box_area(subject) == 0.16
    assert box_height(subject) == 0.4


def test_disjoint_boxes_have_zero_iou() -> None:
    assert box_iou(box(0.0, 0.0, 0.2, 0.2), box(0.5, 0.5, 0.8, 0.8)) == 0.0


def test_identical_boxes_have_iou_one() -> None:
    subject = box(0.1, 0.1, 0.4, 0.5)
    assert box_iou(subject, subject) == 1.0


def test_thirds_proximity_is_one_on_an_intersection() -> None:
    score = thirds_proximity((1.0 / 3.0, 1.0 / 3.0), 0.18)
    assert score == 1.0


def test_center_proximity_is_one_at_the_center() -> None:
    assert center_proximity((0.5, 0.5), 0.18) == 1.0


def test_thirds_proximity_is_not_called_quality() -> None:
    """The function name is proximity. A corner is far from every intersection."""
    score = thirds_proximity((0.05, 0.05), 0.18)
    assert 0.0 <= score < 0.2


def test_non_positive_sigma_scores_zero() -> None:
    assert proximity_score(0.1, 0.0) == 0.0


def test_zero_area_boxes_have_zero_iou() -> None:
    class _Zero:
        x_min = 0.0
        y_min = 0.0
        x_max = 0.0
        y_max = 0.0

    assert box_iou(_Zero(), _Zero()) == 0.0  # type: ignore[arg-type]


def test_vertical_truncation_requires_both_edges() -> None:
    assert is_vertically_truncated(box(0.2, 0.0, 0.5, 1.0), 0.02)
    assert not is_vertically_truncated(box(0.2, 0.1, 0.5, 0.9), 0.02)
    assert math.isfinite(box_iou(box(0.0, 0.0, 0.1, 0.1), box(0.05, 0.05, 0.2, 0.2)))
