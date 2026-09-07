"""Probed media identity and the sampling plan derived from it."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.time import Rational
from cine_analyzer.domain.types import SCHEMA_VERSION, Sha256Hex, StrictModel

__all__ = [
    "ROTATION_DEGREES",
    "SamplePurpose",
    "SampleRequest",
    "SampleResult",
    "SampleStatus",
    "SamplingManifest",
    "SamplingPlan",
    "VideoMetadata",
]

ROTATION_DEGREES = (0, 90, 180, 270)


class SamplePurpose(StrEnum):
    """Why a sample was requested. A sample may serve more than one purpose."""

    CHROMATIC = "CHROMATIC"
    COMPOSITION = "COMPOSITION"
    MOTION = "MOTION"
    EVIDENCE = "EVIDENCE"


class SampleStatus(StrEnum):
    """Outcome of one extract. Cross-shot substitution is never silent success."""

    DECODED = "DECODED"
    UNAVAILABLE = "UNAVAILABLE"


class VideoMetadata(StrictModel):
    """Facts taken from a successful probe. Filename is stored, never echoed in errors."""

    video_id: UUID
    original_filename: Annotated[str, Field(min_length=1, max_length=512)]
    content_sha256: Sha256Hex
    size_bytes: Annotated[int, Field(gt=0, description="Uploaded bytes.")]
    duration_ms: Annotated[
        int,
        Field(gt=0, description="Probed media duration, integer milliseconds."),
    ]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    display_rotation_degrees: Annotated[
        int,
        Field(description="Container rotation applied once before spatial measurement."),
    ]
    average_frame_rate: Rational
    real_frame_rate: Rational | None = None
    video_codec: Annotated[str, Field(min_length=1, max_length=64)]
    pixel_format: str | None = None
    has_audio: bool
    audio_codec: str | None = None
    probe_artifact: ArtifactRef

    @model_validator(mode="after")
    def rotation_is_a_right_angle(self) -> Self:
        if self.display_rotation_degrees not in ROTATION_DEGREES:
            message = "display_rotation_degrees must be 0, 90, 180, or 270"
            raise ValueError(message)
        if self.has_audio and (self.audio_codec is None or self.audio_codec == ""):
            message = "audio_codec is required when has_audio is true"
            raise ValueError(message)
        if not self.has_audio and self.audio_codec is not None:
            message = "audio_codec must be absent when has_audio is false"
            raise ValueError(message)
        return self


class SampleRequest(StrictModel):
    """One planned decode. The plan names the timestamp; it does not carry pixels."""

    sample_id: UUID
    shot_id: UUID
    requested_ms: Annotated[
        int,
        Field(ge=0, description="Requested media timestamp, integer milliseconds."),
    ]
    purposes: Annotated[tuple[SamplePurpose, ...], Field(min_length=1)]


class SamplingPlan(StrictModel):
    """Deterministic list of samples an analysis will decode."""

    schema_version: Annotated[str, Field(description="Sampling-plan schema version.")]
    analysis_id: UUID
    video_id: UUID
    method_version: Annotated[str, Field(min_length=1, max_length=64)]
    requests: tuple[SampleRequest, ...]

    @model_validator(mode="after")
    def schema_is_supported_and_ids_are_unique(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported sampling-plan schema_version {self.schema_version!r}"
            raise ValueError(message)
        sample_ids = [request.sample_id for request in self.requests]
        if len(sample_ids) != len(set(sample_ids)):
            message = "sample_id values must be unique within a sampling plan"
            raise ValueError(message)
        return self


class SampleResult(StrictModel):
    """One extracted sample, or an explicit unavailable outcome."""

    sample_id: UUID
    shot_id: UUID
    requested_ms: Annotated[
        int,
        Field(ge=0, description="Requested media timestamp, integer milliseconds."),
    ]
    decoded_ms: (
        Annotated[
            int,
            Field(ge=0, description="Actual decoded media timestamp, integer milliseconds."),
        ]
        | None
    ) = None
    frame_index: Annotated[int, Field(ge=0)] | None = None
    purposes: Annotated[tuple[SamplePurpose, ...], Field(min_length=1)]
    status: SampleStatus
    image: ArtifactRef | None = None
    unavailable_reason: Annotated[str, Field(min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def decoded_and_unavailable_are_consistent(self) -> Self:
        if self.status is SampleStatus.DECODED:
            if self.image is None or self.decoded_ms is None:
                message = "a decoded sample requires decoded_ms and an image artifact"
                raise ValueError(message)
            if self.unavailable_reason is not None:
                message = "a decoded sample cannot carry an unavailable reason"
                raise ValueError(message)
            return self
        if self.image is not None or self.decoded_ms is not None:
            message = "an unavailable sample cannot carry decoded pixels or a timestamp"
            raise ValueError(message)
        if self.unavailable_reason is None:
            message = "an unavailable sample requires a reason"
            raise ValueError(message)
        return self


class SamplingManifest(StrictModel):
    """Plan plus per-request extract outcomes. Stage output, not a queue payload."""

    schema_version: Annotated[str, Field(description="Sampling-manifest schema version.")]
    analysis_id: UUID
    video_id: UUID
    method_version: Annotated[str, Field(min_length=1, max_length=64)]
    plan: SamplingPlan
    results: tuple[SampleResult, ...]

    @model_validator(mode="after")
    def schema_is_supported_and_results_match_the_plan(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported sampling-manifest schema_version {self.schema_version!r}"
            raise ValueError(message)
        if self.plan.analysis_id != self.analysis_id or self.plan.video_id != self.video_id:
            message = "manifest identity must match the embedded plan"
            raise ValueError(message)
        plan_ids = [request.sample_id for request in self.plan.requests]
        result_ids = [result.sample_id for result in self.results]
        if plan_ids != result_ids:
            message = "manifest results must follow the plan request order and ids"
            raise ValueError(message)
        return self
