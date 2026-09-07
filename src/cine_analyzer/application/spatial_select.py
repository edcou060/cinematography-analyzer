"""Deterministic primary-track selection. Not character identity."""

from collections import defaultdict

from cine_analyzer.application.spatial_geometry import box_area
from cine_analyzer.domain.config import SpatialConfig
from cine_analyzer.domain.spatial import SubjectObservation

__all__ = ["CoverageAreaConfidenceSelector", "track_coverage"]


def track_coverage(
    observations: tuple[SubjectObservation, ...],
    sample_count: int,
    track_id: str,
) -> float:
    """Fraction of sampled frames that contain ``track_id``."""
    if sample_count <= 0:
        return 0.0
    frames = {item.sample_id for item in observations if item.track_id == track_id}
    return len(frames) / sample_count


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


class CoverageAreaConfidenceSelector:
    """Score = 0.45 coverage + 0.35 median area + 0.20 median confidence."""

    def select(
        self,
        observations: tuple[SubjectObservation, ...],
        sample_count: int,
        config: SpatialConfig,
    ) -> str | None:
        """Return the winning track id, or None when none is stable."""
        if not observations or sample_count <= 0:
            return None
        grouped: dict[str, list[SubjectObservation]] = defaultdict(list)
        for item in observations:
            grouped[item.track_id].append(item)
        ranked: list[tuple[float, str]] = []
        weights = config.primary_track_weights
        floor = config.framing_rules.min_track_coverage
        for track_id, members in grouped.items():
            coverage = track_coverage(observations, sample_count, track_id)
            if coverage < floor:
                continue
            area = _median([box_area(item.box) for item in members])
            confidence = _median([item.detector_confidence for item in members])
            score = (
                weights.coverage * coverage
                + weights.median_area * area
                + weights.median_confidence * confidence
            )
            ranked.append((score, track_id))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return ranked[0][1]
