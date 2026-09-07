"""Box geometry: IoU, area, proximity. Pure Python; thirds is proximity, not quality."""

import math

from cine_analyzer.domain.spatial import BoxNorm

__all__ = [
    "THIRDS_INTERSECTIONS",
    "box_area",
    "box_centroid",
    "box_height",
    "box_iou",
    "center_proximity",
    "is_vertically_truncated",
    "proximity_score",
    "thirds_proximity",
]

THIRDS_INTERSECTIONS: tuple[tuple[float, float], ...] = (
    (1.0 / 3.0, 1.0 / 3.0),
    (2.0 / 3.0, 1.0 / 3.0),
    (1.0 / 3.0, 2.0 / 3.0),
    (2.0 / 3.0, 2.0 / 3.0),
)
_CENTER = (0.5, 0.5)


def box_centroid(box: BoxNorm) -> tuple[float, float]:
    """Normalised box centre."""
    return ((box.x_min + box.x_max) / 2.0, (box.y_min + box.y_max) / 2.0)


def box_area(box: BoxNorm) -> float:
    """Normalised box area in ``[0, 1]``."""
    return (box.x_max - box.x_min) * (box.y_max - box.y_min)


def box_height(box: BoxNorm) -> float:
    """Person height ratio: box height in normalised image coordinates."""
    return box.y_max - box.y_min


def box_iou(left: BoxNorm, right: BoxNorm) -> float:
    """Intersection-over-union of two normalised boxes."""
    x_min = max(left.x_min, right.x_min)
    y_min = max(left.y_min, right.y_min)
    x_max = min(left.x_max, right.x_max)
    y_max = min(left.y_max, right.y_max)
    width = max(0.0, x_max - x_min)
    height = max(0.0, y_max - y_min)
    intersection = width * height
    union = box_area(left) + box_area(right) - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def is_vertically_truncated(box: BoxNorm, edge: float) -> bool:
    """True when the box touches both the top and bottom within ``edge``."""
    return box.y_min <= edge and box.y_max >= 1.0 - edge


def proximity_score(distance: float, sigma: float) -> float:
    """``exp(-(d/sigma)^2)`` clipped to ``[0, 1]``."""
    if sigma <= 0.0:
        return 0.0
    score = math.exp(-((distance / sigma) ** 2))
    return max(0.0, min(1.0, score))


def _nearest_distance(
    point: tuple[float, float], targets: tuple[tuple[float, float], ...]
) -> float:
    best = float("inf")
    for target in targets:
        delta_x = point[0] - target[0]
        delta_y = point[1] - target[1]
        distance = math.sqrt(delta_x * delta_x + delta_y * delta_y)
        best = min(best, distance)
    return best


def thirds_proximity(centroid: tuple[float, float], sigma: float) -> float:
    """Geometric proximity to the nearest rule-of-thirds intersection."""
    return proximity_score(_nearest_distance(centroid, THIRDS_INTERSECTIONS), sigma)


def center_proximity(centroid: tuple[float, float], sigma: float) -> float:
    """Geometric proximity to the frame centre."""
    return proximity_score(_nearest_distance(centroid, (_CENTER,)), sigma)
