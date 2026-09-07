"""Shared spatial test helpers."""

from uuid import UUID, uuid4

import numpy as np
from numpy.typing import NDArray
from tests.unit.chromatic.jpeg_util import encode_jpeg, solid_rgb

from cine_analyzer.adapters.vision.fake_subject import FakeSubjectDetector
from cine_analyzer.adapters.vision.opencv_overlay import OpenCvOverlayRenderer
from cine_analyzer.application.spatial import SpatialShotAnalyzer
from cine_analyzer.application.spatial_select import CoverageAreaConfidenceSelector
from cine_analyzer.application.spatial_track import IoUSubjectTracker
from cine_analyzer.domain.config import AnalysisConfig, SpatialConfig
from cine_analyzer.domain.spatial import BoxNorm
from cine_analyzer.ports.spatial import DetectionHit, SpatialFrame


def spatial_config(**overrides: object) -> SpatialConfig:
    base = AnalysisConfig().spatial
    if not overrides:
        return base
    return base.model_copy(update=overrides)


def fake_analyzer(
    script: dict[UUID, tuple[DetectionHit, ...]] | None = None,
) -> SpatialShotAnalyzer:
    return SpatialShotAnalyzer(
        {"fake": FakeSubjectDetector(script)},
        IoUSubjectTracker(),
        CoverageAreaConfidenceSelector(),
        OpenCvOverlayRenderer(),
    )


def hit(
    sample_id: UUID,
    subject: BoxNorm,
    *,
    confidence: float = 0.9,
    class_name: str = "person",
) -> DetectionHit:
    return DetectionHit(
        sample_id=sample_id,
        class_name=class_name,
        detector_confidence=confidence,
        box=subject,
    )


def frame_from_rgb(rgb: NDArray[np.uint8], sample_id: UUID | None = None) -> SpatialFrame:
    return SpatialFrame(sample_id=sample_id or uuid4(), jpeg=encode_jpeg(rgb))


def gray_frame(sample_id: UUID | None = None) -> SpatialFrame:
    return frame_from_rgb(solid_rgb((64, 64, 64), size=48), sample_id)


def magenta_person_rgb(*, width: int = 64, height: int = 48) -> NDArray[np.uint8]:
    """Gray field with a magenta rectangle at height ratio 0.50 near a thirds point."""
    frame = np.full((height, width, 3), 64, dtype=np.uint8)
    y0, y1 = int(height * 0.10), int(height * 0.60)
    x0, x1 = int(width * 0.23), int(width * 0.43)
    frame[y0:y1, x0:x1] = (255, 0, 255)
    return frame


def magenta_frame(sample_id: UUID | None = None) -> SpatialFrame:
    return frame_from_rgb(magenta_person_rgb(), sample_id)


def box(x_min: float, y_min: float, x_max: float, y_max: float) -> BoxNorm:
    return BoxNorm(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)
