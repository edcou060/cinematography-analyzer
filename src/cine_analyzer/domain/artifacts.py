"""Artifact references, frame evidence, and method provenance.

Cross-process messages carry these identifiers, never the bytes they name.
"""

from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from cine_analyzer.domain.types import Sha256Hex, StrictModel

__all__ = ["ArtifactRef", "EvidenceFrame", "MethodProvenance"]


class ArtifactRef(StrictModel):
    """Content-addressed pointer to an immutable blob."""

    artifact_id: UUID
    kind: Annotated[str, Field(min_length=1, max_length=64)]
    media_type: Annotated[str, Field(min_length=1, max_length=128)]
    sha256: Sha256Hex
    size_bytes: Annotated[
        int,
        Field(ge=0, description="Artifact size in bytes, not a media duration."),
    ]
    schema_version: str | None = None


class EvidenceFrame(StrictModel):
    """One decoded sample used as evidence for a metric.

    ``requested_ms`` and ``decoded_ms`` are both stored because a millisecond
    value cannot round-trip to a frame index under a variable frame rate.
    """

    sample_id: UUID
    requested_ms: Annotated[
        int,
        Field(ge=0, description="Requested media timestamp, integer milliseconds."),
    ]
    decoded_ms: Annotated[
        int,
        Field(ge=0, description="Actual decoded media timestamp, integer milliseconds."),
    ]
    frame_index: Annotated[int, Field(ge=0)] | None = None
    image: ArtifactRef
    purposes: tuple[str, ...]


class MethodProvenance(StrictModel):
    """How a value was produced, including the hashed analysis configuration."""

    method: Annotated[str, Field(min_length=1, max_length=128)]
    method_version: Annotated[str, Field(min_length=1, max_length=64)]
    config_hash: Sha256Hex
    code_revision: Annotated[str, Field(min_length=1, max_length=128)]
    random_seed: int | None = None
    model_name: str | None = None
    model_package_version: str | None = None
    weights_sha256: Sha256Hex | None = None
    device: str | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def completion_does_not_precede_start(self) -> Self:
        if self.completed_at < self.started_at:
            message = "completed_at must not precede started_at"
            raise ValueError(message)
        return self
