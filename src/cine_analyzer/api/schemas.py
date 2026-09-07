"""Public HTTP envelopes. Domain report/status models are reused where they already fit."""

from typing import Literal
from uuid import UUID

from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.timeline import TimelinePoint
from cine_analyzer.domain.types import StrictModel

__all__ = [
    "AnalysisAccepted",
    "AnalysisCreateRequest",
    "HealthResponse",
    "TimelineWindowResponse",
    "VideoAccepted",
]


class HealthResponse(StrictModel):
    """Liveness or readiness payload."""

    status: Literal["ok", "unavailable"]


class VideoAccepted(StrictModel):
    """Identity returned after a streamed upload."""

    video_id: UUID
    content_sha256: str
    reused: bool
    duration_ms: int
    width: int
    height: int
    has_audio: bool


class AnalysisCreateRequest(StrictModel):
    """Start or reuse an analysis for an existing video."""

    video_id: UUID
    config: AnalysisConfig | None = None


class AnalysisAccepted(StrictModel):
    """Asynchronous analysis creation. Poll status; do not assume completion."""

    analysis_id: UUID
    video_id: UUID
    configuration_hash: str
    pipeline_version: str
    reused: bool
    state: AnalysisState


class TimelineWindowResponse(StrictModel):
    """Bounded timeline slice. Points are already downsampled."""

    analysis_id: UUID
    start_ms: int
    end_ms: int
    max_points: int
    points: tuple[TimelinePoint, ...]
