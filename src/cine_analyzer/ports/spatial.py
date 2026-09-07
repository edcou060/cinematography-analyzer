"""Spatial analysis ports. Detector SDKs stay in adapters."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from cine_analyzer.domain.config import SpatialConfig
from cine_analyzer.domain.spatial import BoxNorm, SpatialValue, SubjectObservation
from cine_analyzer.domain.types import MetricStatus

__all__ = [
    "DetectionHit",
    "OverlayRenderer",
    "PrimarySubjectSelector",
    "SpatialAnalyzer",
    "SpatialComputeResult",
    "SpatialFrame",
    "SubjectDetector",
    "SubjectTracker",
]


@dataclass(frozen=True, slots=True)
class SpatialFrame:
    """One decoded composition JPEG used as a spatial sample."""

    sample_id: UUID
    jpeg: bytes


@dataclass(frozen=True, slots=True)
class DetectionHit:
    """Detector output before tracking. ``track_id`` does not exist yet."""

    sample_id: UUID
    class_name: str
    detector_confidence: float
    box: BoxNorm


@dataclass(frozen=True, slots=True)
class SpatialComputeResult:
    """Adapter/application output before provenance is attached."""

    status: MetricStatus
    value: SpatialValue | None
    confidence: float | None
    reason_code: str | None
    evidence_sample_ids: tuple[UUID, ...]
    observations: tuple[SubjectObservation, ...]
    overlays: tuple[tuple[UUID, bytes], ...]


class SubjectDetector(Protocol):
    """Produce person boxes for one shot's sampled frames."""

    def infer(
        self,
        frames: tuple[SpatialFrame, ...],
        config: SpatialConfig,
    ) -> tuple[DetectionHit, ...]:
        """Return hits with validated boxes. Paths never appear in errors."""


class SubjectTracker(Protocol):
    """Associate hits within one shot. Reset is the caller's empty shot."""

    def track(
        self,
        hits: tuple[DetectionHit, ...],
        sample_ids: tuple[UUID, ...],
        config: SpatialConfig,
    ) -> tuple[SubjectObservation, ...]:
        """Assign track ids and centroids. Does not cross shot boundaries."""


class PrimarySubjectSelector(Protocol):
    """Choose the most continuously prominent person track, not a character."""

    def select(
        self,
        observations: tuple[SubjectObservation, ...],
        sample_count: int,
        config: SpatialConfig,
    ) -> str | None:
        """Return a track id or None when no stable candidate exists."""


class OverlayRenderer(Protocol):
    """Draw boxes, centroids, thirds, and center guides on a JPEG copy."""

    def render(
        self,
        jpeg: bytes,
        observations: tuple[SubjectObservation, ...],
        primary_track_id: str | None,
    ) -> bytes | None:
        """Return overlay JPEG bytes, or None when the source cannot be decoded."""


class SpatialAnalyzer(Protocol):
    """Measure one shot: detect, track, select, geometry, overlay."""

    def analyze_shot(
        self,
        frames: tuple[SpatialFrame, ...],
        config: SpatialConfig,
    ) -> SpatialComputeResult:
        """Return a value or a named absence. Paths never appear in errors."""
