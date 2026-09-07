"""Deterministic fake person detector (ADR-0014). No licensed SDK."""

from uuid import UUID

from cine_analyzer.domain.config import SpatialConfig
from cine_analyzer.domain.spatial import BoxNorm
from cine_analyzer.ports.spatial import DetectionHit, SpatialFrame

__all__ = ["FakeSubjectDetector"]

_PERSON = "person"
_MIN_BLOB_PIXELS = 8
_IMAGE_NDIM = 3
_COLOR_CHANNELS = 3


class FakeSubjectDetector:
    """Scripted hits by sample id, else a magenta-blob probe for fixtures."""

    def __init__(
        self,
        script: dict[UUID, tuple[DetectionHit, ...]] | None = None,
    ) -> None:
        self._script = script or {}

    def infer(
        self,
        frames: tuple[SpatialFrame, ...],
        config: SpatialConfig,
    ) -> tuple[DetectionHit, ...]:
        """Return scripted boxes, or magenta rectangles found in JPEG pixels."""
        hits: list[DetectionHit] = []
        for frame in frames:
            if frame.sample_id in self._script:
                hits.extend(self._script[frame.sample_id])
                continue
            found = _magenta_hit(frame, config.person_confidence)
            if found is not None:
                hits.append(found)
        return tuple(hits)


def _magenta_hit(frame: SpatialFrame, confidence: float) -> DetectionHit | None:
    import numpy as np

    from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2

    cv2 = load_cv2()
    array = np.frombuffer(frame.jpeg, dtype=np.uint8)
    bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if (
        bgr is None
        or bgr.ndim != _IMAGE_NDIM
        or bgr.shape[0] <= 0
        or bgr.shape[1] <= 0
        or bgr.shape[2] != _COLOR_CHANNELS
    ):
        return None
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lower = np.array([130, 80, 80], dtype=np.uint8)
    upper = np.array([170, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    ys, xs = np.where(mask > 0)
    if xs.size < _MIN_BLOB_PIXELS:
        return None
    height, width = mask.shape
    x_min = float(xs.min()) / width
    y_min = float(ys.min()) / height
    x_max = float(xs.max() + 1) / width
    y_max = float(ys.max() + 1) / height
    if x_max <= x_min or y_max <= y_min:
        return None
    return DetectionHit(
        sample_id=frame.sample_id,
        class_name=_PERSON,
        detector_confidence=max(confidence, 0.9),
        box=BoxNorm(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max),
    )
