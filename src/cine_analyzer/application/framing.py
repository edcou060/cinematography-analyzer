"""Versioned framing-key estimates from person height, truncation, and agreement."""

from cine_analyzer.application.spatial_geometry import box_height, is_vertically_truncated
from cine_analyzer.domain.config import FramingRules
from cine_analyzer.domain.spatial import FramingLabel, SubjectObservation

__all__ = ["estimate_framing", "framing_confidence", "label_observation"]


def label_observation(observation: SubjectObservation, rules: FramingRules) -> FramingLabel:
    """Map one box to a framing estimate. Truncation can force extreme close-up."""
    if is_vertically_truncated(observation.box, rules.edge_truncation):
        return FramingLabel.EXTREME_CLOSE_UP_ESTIMATE
    height = box_height(observation.box)
    if height < rules.extreme_wide_height_max:
        return FramingLabel.EXTREME_WIDE_ESTIMATE
    if height < rules.wide_height_max:
        return FramingLabel.WIDE_ESTIMATE
    if height < rules.medium_height_max:
        return FramingLabel.MEDIUM_ESTIMATE
    if height < rules.close_up_height_max:
        return FramingLabel.CLOSE_UP_ESTIMATE
    return FramingLabel.EXTREME_CLOSE_UP_ESTIMATE


def estimate_framing(
    observations: tuple[SubjectObservation, ...],
    rules: FramingRules,
) -> FramingLabel:
    """Majority label, or ``UNDETERMINED`` when samples disagree too often."""
    if not observations:
        return FramingLabel.UNDETERMINED
    labels = [label_observation(item, rules) for item in observations]
    counts: dict[FramingLabel, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    winner, wins = max(
        counts.items(),
        key=lambda item: (item[1], -list(FramingLabel).index(item[0])),
    )
    if (1.0 - wins / len(labels)) > rules.disagreement_fraction:
        return FramingLabel.UNDETERMINED
    return winner


def framing_confidence(
    label: FramingLabel,
    observations: tuple[SubjectObservation, ...],
    rules: FramingRules,
    track_coverage_ratio: float,
) -> float:
    """Uncalibrated heuristic in ``[0, 1]``. Distance from thresholds plus agreement."""
    if not observations:
        return 0.0
    detector = _median([item.detector_confidence for item in observations])
    labels = [label_observation(item, rules) for item in observations]
    if label is FramingLabel.UNDETERMINED:
        return _clip(0.25 * detector + 0.35 * track_coverage_ratio)
    agreement = labels.count(label) / len(labels)
    heights = sorted(box_height(item.box) for item in observations)
    median_height = heights[len(heights) // 2]
    margin = _threshold_margin(median_height, rules)
    return _clip(0.35 * detector + 0.30 * track_coverage_ratio + 0.20 * agreement + 0.15 * margin)


def _threshold_margin(height: float, rules: FramingRules) -> float:
    bounds = (
        0.0,
        rules.extreme_wide_height_max,
        rules.wide_height_max,
        rules.medium_height_max,
        rules.close_up_height_max,
        1.0,
    )
    nearest = min(abs(height - bound) for bound in bounds)
    return _clip(nearest / 0.08)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))
