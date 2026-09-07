"""Versioned analysis report. Interpretation is optional and cannot write a metric."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.chromatics import ChromaticMeasurement
from cine_analyzer.domain.media import VideoMetadata
from cine_analyzer.domain.shots import Shot
from cine_analyzer.domain.spatial import SpatialMeasurement
from cine_analyzer.domain.temporal import TemporalMeasurement
from cine_analyzer.domain.types import (
    SCHEMA_VERSION,
    MetricStatus,
    NonNegativeFloat,
    Sha256Hex,
    StrictModel,
)

__all__ = [
    "AnalysisReport",
    "Critique",
    "ReportAvailability",
    "ShotAnalysis",
    "StageAvailability",
    "VideoSummary",
]


class StageAvailability(StrEnum):
    """Whether a pillar produced values, produced some, was skipped, or was not asked."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_REQUESTED = "NOT_REQUESTED"


class ReportAvailability(StrictModel):
    """Typed per-pillar availability. Absence is a status, not a missing key."""

    shots: StageAvailability
    chromatic: StageAvailability
    spatial: StageAvailability
    motion: StageAvailability
    audio: StageAvailability
    tension: StageAvailability
    critic: StageAvailability


class ShotAnalysis(StrictModel):
    """One shot and the three per-shot measurement envelopes."""

    shot: Shot
    chromatic: ChromaticMeasurement
    spatial: SpatialMeasurement
    temporal: TemporalMeasurement


class VideoSummary(StrictModel):
    """Editing summary. Mean and median are float milliseconds (even-count medians)."""

    shot_count: Annotated[int, Field(ge=1)]
    average_shot_length_ms: Annotated[
        float,
        Field(
            gt=0,
            description=(
                "Mean shot duration in milliseconds. Float because it is an aggregate, "
                "not a timeline instant."
            ),
        ),
    ]
    median_shot_length_ms: Annotated[
        float,
        Field(
            gt=0,
            description=(
                "Median shot duration in milliseconds. Float because an even shot count "
                "averages two integer durations."
            ),
        ),
    ]
    shots_per_minute: NonNegativeFloat


class Critique(StrictModel):
    """Optional interpretation of an already-validated report. Regenerable; cannot write metrics."""

    status: MetricStatus
    text: Annotated[str, Field(max_length=1200)] | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    input_report_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def status_matches_text(self) -> Self:
        if self.status is MetricStatus.OK:
            if self.text is None or self.text == "":
                message = "OK critique requires text"
                raise ValueError(message)
            return self
        if self.text is not None:
            message = "non-OK critique must not contain text"
            raise ValueError(message)
        return self


class AnalysisReport(StrictModel):
    """The versioned document a client reads. Large series live behind artifact references."""

    schema_version: Annotated[str, Field(description="Report schema version.")]
    analysis_id: UUID
    video: VideoMetadata
    generated_at: AwareDatetime
    pipeline_version: Annotated[str, Field(min_length=1, max_length=64)]
    configuration_hash: Sha256Hex
    availability: ReportAvailability
    summary: VideoSummary
    shots: Annotated[tuple[ShotAnalysis, ...], Field(min_length=1)]
    timeline_artifact: ArtifactRef | None = None
    critique: Critique | None = None

    @model_validator(mode="after")
    def report_is_internally_consistent(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported report schema_version {self.schema_version!r}"
            raise ValueError(message)
        if self.summary.shot_count != len(self.shots):
            message = "summary.shot_count must equal the number of shot analyses"
            raise ValueError(message)
        for expected_index, item in enumerate(self.shots):
            if item.shot.index != expected_index:
                message = "report shot indices must be contiguous from zero"
                raise ValueError(message)
        if self.video.has_audio is False and self.availability.audio is StageAvailability.COMPLETE:
            message = "audio cannot be COMPLETE when the source has no audio stream"
            raise ValueError(message)
        return self
