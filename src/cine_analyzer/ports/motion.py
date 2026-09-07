"""Motion analysis port. OpenCV stays in the adapter."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from cine_analyzer.domain.config import MotionConfig
from cine_analyzer.domain.spatial import BoxNorm

__all__ = ["FlowPairStats", "MotionAnalyzer", "MotionFrame", "MotionPairInput"]


@dataclass(frozen=True, slots=True)
class MotionFrame:
    """One decoded motion JPEG with its presentation timestamp."""

    sample_id: UUID
    jpeg: bytes
    decoded_ms: int


@dataclass(frozen=True, slots=True)
class MotionPairInput:
    """Adjacent samples inside one shot. Never spans a detected cut."""

    sample_id_a: UUID
    sample_id_b: UUID
    jpeg_a: bytes
    jpeg_b: bytes
    dt_ms: int
    at_ms: int
    subject_boxes: tuple[BoxNorm, ...]


@dataclass(frozen=True, slots=True)
class FlowPairStats:
    """Global and residual magnitudes for one adjacent pair. No camera-movement labels."""

    sample_id_a: UUID
    sample_id_b: UUID
    dt_ms: int
    at_ms: int
    global_dx: float
    global_dy: float
    global_magnitude: float
    residual_magnitude_median: float
    residual_magnitude_p90: float
    valid_ratio: float
    flagged_discontinuity: bool


class MotionAnalyzer(Protocol):
    """Dense flow between two JPEGs. Returns None when the pair cannot be measured."""

    def analyze_pair(self, pair: MotionPairInput, config: MotionConfig) -> FlowPairStats | None:
        """Compute Farneback stats. Paths never appear in errors."""
