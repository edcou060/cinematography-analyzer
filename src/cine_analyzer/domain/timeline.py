"""Windowed timeline points. Large series live in an artifact, not the report body."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from cine_analyzer.domain.config import TensionWeights
from cine_analyzer.domain.temporal import AudioWindowValue, TensionComponents
from cine_analyzer.domain.types import SCHEMA_VERSION, StrictModel

__all__ = ["TENSION_METHOD_VERSION", "Timeline", "TimelinePoint"]

TENSION_METHOD_VERSION = "tension-v1"
_DEFAULT_WEIGHTS = TensionWeights(cut_activity=0.35, audio_activity=0.30, motion=0.35)


class TimelinePoint(StrictModel):
    """One instant on the analysis timeline, with every tension component retained."""

    at_ms: Annotated[
        int,
        Field(ge=0, description="Timeline instant, integer milliseconds."),
    ]
    shot_index: Annotated[int, Field(ge=0)]
    tension: TensionComponents
    audio: AudioWindowValue | None = None


class Timeline(StrictModel):
    """Ordered series of timeline points for one analysis."""

    schema_version: Annotated[str, Field(description="Timeline schema version.")]
    analysis_id: UUID
    hop_ms: Annotated[int, Field(ge=1, description="Timeline hop, integer milliseconds.")] = 500
    window_ms: Annotated[
        int,
        Field(ge=1, description="Audio feature window, integer milliseconds."),
    ] = 1000
    method_version: Annotated[str, Field(min_length=1, max_length=64)] = TENSION_METHOD_VERSION
    weights: TensionWeights = _DEFAULT_WEIGHTS
    effective_weights: TensionWeights = _DEFAULT_WEIGHTS
    warnings: tuple[str, ...] = ()
    points: tuple[TimelinePoint, ...] = ()

    @model_validator(mode="after")
    def points_are_strictly_increasing(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported timeline schema_version {self.schema_version!r}"
            raise ValueError(message)
        for left, right in zip(self.points, self.points[1:], strict=False):
            if right.at_ms <= left.at_ms:
                message = "timeline points must be strictly increasing in at_ms"
                raise ValueError(message)
        return self
