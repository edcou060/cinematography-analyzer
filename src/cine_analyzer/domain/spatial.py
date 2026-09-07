"""Spatial measurements: subject geometry, framing estimates, thirds proximity."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.measurements import Measurement
from cine_analyzer.domain.types import Score, StrictModel

__all__ = [
    "BoxNorm",
    "FramingLabel",
    "SpatialMeasurement",
    "SpatialValue",
    "SubjectObservation",
]


class BoxNorm(StrictModel):
    """Axis-aligned box in normalised image coordinates, origin at top-left."""

    x_min: Score
    y_min: Score
    x_max: Score
    y_max: Score

    @model_validator(mode="after")
    def valid_box(self) -> Self:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            message = "invalid normalized box"
            raise ValueError(message)
        return self


class SubjectObservation(StrictModel):
    """One detector observation on one sample. Not an identity."""

    track_id: Annotated[str, Field(min_length=1, max_length=128)]
    sample_id: UUID
    class_name: Annotated[str, Field(min_length=1, max_length=64)]
    detector_confidence: Score
    box: BoxNorm
    centroid_x: Score
    centroid_y: Score
    mask_artifact: ArtifactRef | None = None

    @model_validator(mode="after")
    def centroid_lies_inside_the_box(self) -> Self:
        if not (self.box.x_min <= self.centroid_x <= self.box.x_max):
            message = "centroid_x must lie within the normalized box"
            raise ValueError(message)
        if not (self.box.y_min <= self.centroid_y <= self.box.y_max):
            message = "centroid_y must lie within the normalized box"
            raise ValueError(message)
        return self


class FramingLabel(StrEnum):
    """Heuristic shot-size estimate. Abstains rather than guessing."""

    EXTREME_WIDE_ESTIMATE = "EXTREME_WIDE_ESTIMATE"
    WIDE_ESTIMATE = "WIDE_ESTIMATE"
    MEDIUM_ESTIMATE = "MEDIUM_ESTIMATE"
    CLOSE_UP_ESTIMATE = "CLOSE_UP_ESTIMATE"
    EXTREME_CLOSE_UP_ESTIMATE = "EXTREME_CLOSE_UP_ESTIMATE"
    UNDETERMINED = "UNDETERMINED"


class SpatialValue(StrictModel):
    """Per-shot spatial summary. Primary-track selection is a documented rule, not recognition."""

    primary_track_id: Annotated[str, Field(min_length=1, max_length=128)]
    subject_coverage_ratio_median: Score
    subject_height_ratio_median: Score
    thirds_proximity_score: Score
    thirds_proximity_p10: Score
    center_proximity_score: Score
    framing: FramingLabel
    framing_confidence: Score
    track_coverage_ratio: Score


SpatialMeasurement = Measurement[SpatialValue]
