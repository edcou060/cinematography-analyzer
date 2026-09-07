"""Chromatic analysis port. OpenCV and sklearn stay in the adapter."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from cine_analyzer.domain.chromatics import ChromaticValue
from cine_analyzer.domain.config import ChromaticConfig
from cine_analyzer.domain.types import MetricStatus

__all__ = ["ChromaticAnalyzer", "ChromaticComputeResult", "ChromaticFrame"]


@dataclass(frozen=True, slots=True)
class ChromaticFrame:
    """One decoded evidence JPEG used as a chromatic sample."""

    sample_id: UUID
    jpeg: bytes


@dataclass(frozen=True, slots=True)
class ChromaticComputeResult:
    """Adapter output before application provenance is attached."""

    status: MetricStatus
    value: ChromaticValue | None
    confidence: float | None
    reason_code: str | None
    evidence_sample_ids: tuple[UUID, ...]


class ChromaticAnalyzer(Protocol):
    """Measure palette and lightness for one shot's sampled frames."""

    def analyze_shot(
        self,
        frames: tuple[ChromaticFrame, ...],
        config: ChromaticConfig,
    ) -> ChromaticComputeResult:
        """Return a value or a named absence. Paths never appear in errors."""
