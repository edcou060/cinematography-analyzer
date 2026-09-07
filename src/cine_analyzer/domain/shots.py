"""Detected edit intervals. These are shots, never narrative scenes."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from cine_analyzer.domain.artifacts import MethodProvenance
from cine_analyzer.domain.time import TimeRangeMs
from cine_analyzer.domain.types import SCHEMA_VERSION, StrictModel

__all__ = ["Shot", "ShotBoundary", "ShotSet", "TransitionKind"]


class TransitionKind(StrEnum):
    """Detector classification of a visual transition. Not an editorial verdict."""

    CUT = "CUT"
    FADE = "FADE"
    UNKNOWN = "UNKNOWN"


class ShotBoundary(StrictModel):
    """A detected visual transition on the media timeline."""

    boundary_id: UUID
    position_ms: Annotated[
        int,
        Field(
            gt=0,
            description="Transition position, integer milliseconds. Clip start is not a boundary.",
        ),
    ]
    transition: TransitionKind
    detector_score: float | None = None
    evidence_before: UUID | None = None
    evidence_after: UUID | None = None


class Shot(StrictModel):
    """Half-open interval between two consecutive boundaries, plus clip start and end."""

    shot_id: UUID
    index: Annotated[int, Field(ge=0)]
    time_range: TimeRangeMs
    incoming_boundary_id: UUID | None = None
    outgoing_boundary_id: UUID | None = None
    representative_sample_id: UUID | None = None


class ShotSet(StrictModel):
    """Ordered, contiguous covering of the analysed timeline by shots."""

    schema_version: Annotated[str, Field(description="Shot-set schema version.")]
    analysis_id: UUID
    detector: MethodProvenance
    shots: Annotated[tuple[Shot, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def shots_are_ordered_and_contiguous(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported shot-set schema_version {self.schema_version!r}"
            raise ValueError(message)
        shot_ids = [shot.shot_id for shot in self.shots]
        if len(shot_ids) != len(set(shot_ids)):
            message = "shot_id values must be unique within a shot set"
            raise ValueError(message)
        for expected_index, shot in enumerate(self.shots):
            if shot.index != expected_index:
                message = "shot indices must be contiguous from zero"
                raise ValueError(message)
        for left, right in zip(self.shots, self.shots[1:], strict=False):
            if left.time_range.end_ms != right.time_range.start_ms:
                message = "shot time ranges must be contiguous"
                raise ValueError(message)
        return self

    def duration_ms(self) -> int:
        """Sum of shot durations. Equals last.end_ms - first.start_ms when contiguous."""
        first = self.shots[0]
        last = self.shots[-1]
        return last.time_range.end_ms - first.time_range.start_ms
