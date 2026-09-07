"""Shot detection and sample extraction ports. Library vocabulary stays in adapters."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from cine_analyzer.domain.config import ShotsConfig
from cine_analyzer.domain.media import SampleRequest
from cine_analyzer.domain.shots import TransitionKind
from cine_analyzer.domain.time import TimeRangeMs

__all__ = [
    "DecodedSample",
    "DetectedBoundary",
    "DetectionResult",
    "SampleExtractor",
    "ShotDetector",
]


@dataclass(frozen=True, slots=True)
class DetectedBoundary:
    """One internal edit. Clip start and end are not included."""

    position_ms: int
    transition: TransitionKind
    detector_score: float | None


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Adapter output after translating third-party interval names to shots."""

    boundaries: tuple[DetectedBoundary, ...]
    debug_stats: bytes | None


@dataclass(frozen=True, slots=True)
class DecodedSample:
    """One extract attempt. ``jpeg`` is set only when status is decoded."""

    sample_id: UUID
    requested_ms: int
    decoded_ms: int | None
    frame_index: int | None
    jpeg: bytes | None
    unavailable_reason: str | None


class ShotDetector(Protocol):
    """Detect internal edit boundaries. Implementations must not use a shell."""

    def detect(self, path: Path, config: ShotsConfig, *, duration_ms: int) -> DetectionResult:
        """Return internal boundaries. Paths never appear in adapter errors."""


class SampleExtractor(Protocol):
    """Decode planned samples in ascending timestamp order."""

    def extract(
        self,
        path: Path,
        requests: tuple[SampleRequest, ...],
        ranges: dict[UUID, TimeRangeMs],
        *,
        rotation_degrees: int,
    ) -> tuple[DecodedSample, ...]:
        """Return one result per request, in request order. No cross-shot substitution."""
