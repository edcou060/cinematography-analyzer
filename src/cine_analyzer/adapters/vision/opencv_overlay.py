"""Evidence overlay: boxes, centroids, thirds, and center guides on a JPEG copy."""

from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2
from cine_analyzer.domain.spatial import SubjectObservation

__all__ = ["OpenCvOverlayRenderer"]

_IMAGE_NDIM = 3
_COLOR_CHANNELS = 3
_PRIMARY_BGR = (0, 220, 0)
_OTHER_BGR = (0, 200, 220)
_GUIDE_BGR = (240, 240, 240)
_CENTER_BGR = (40, 40, 240)


class OpenCvOverlayRenderer:
    """Draw composition guides without mutating the source JPEG bytes."""

    def render(
        self,
        jpeg: bytes,
        observations: tuple[SubjectObservation, ...],
        primary_track_id: str | None,
    ) -> bytes | None:
        """Return a new JPEG, or None when decode fails."""
        cv2 = load_cv2()
        rgb = _decode(jpeg, cv2)
        if rgb is None:
            return None
        canvas = np.copy(rgb)
        height, width = canvas.shape[:2]
        _draw_thirds(canvas, width, height)
        _draw_center(canvas, width, height)
        for item in observations:
            color = _PRIMARY_BGR if item.track_id == primary_track_id else _OTHER_BGR
            _draw_box(canvas, item, width, height, color, cv2)
        return _encode(canvas, cv2)


def _decode(jpeg: bytes, cv2_module: Any) -> NDArray[np.uint8] | None:
    if not jpeg:
        return None
    array = np.frombuffer(jpeg, dtype=np.uint8)
    bgr = cv2_module.imdecode(array, cv2_module.IMREAD_COLOR)
    if bgr is None or bgr.ndim != _IMAGE_NDIM or bgr.shape[2] != _COLOR_CHANNELS:
        return None
    if bgr.shape[0] <= 0 or bgr.shape[1] <= 0:
        return None
    return cast("NDArray[np.uint8]", cv2_module.cvtColor(bgr, cv2_module.COLOR_BGR2RGB))


def _encode(rgb: NDArray[np.uint8], cv2_module: Any) -> bytes | None:
    ok, buffer = cv2_module.imencode(
        ".jpg",
        cv2_module.cvtColor(rgb, cv2_module.COLOR_RGB2BGR),
        [int(cv2_module.IMWRITE_JPEG_QUALITY), 95],
    )
    if not ok:
        return None
    return bytes(buffer.tobytes())


def _draw_thirds(canvas: NDArray[np.uint8], width: int, height: int) -> None:
    for fraction in (1, 2):
        x = int(width * fraction / 3)
        y = int(height * fraction / 3)
        canvas[:, max(0, x - 1) : min(width, x + 1)] = _GUIDE_BGR
        canvas[max(0, y - 1) : min(height, y + 1), :] = _GUIDE_BGR


def _draw_center(canvas: NDArray[np.uint8], width: int, height: int) -> None:
    cx, cy = width // 2, height // 2
    arm = max(4, min(width, height) // 20)
    canvas[cy, max(0, cx - arm) : min(width, cx + arm + 1)] = _CENTER_BGR
    canvas[max(0, cy - arm) : min(height, cy + arm + 1), cx] = _CENTER_BGR


def _draw_box(
    canvas: NDArray[np.uint8],
    item: SubjectObservation,
    width: int,
    height: int,
    color: tuple[int, int, int],
    cv2_module: Any,
) -> None:
    x_min = int(item.box.x_min * width)
    y_min = int(item.box.y_min * height)
    x_max = int(item.box.x_max * width)
    y_max = int(item.box.y_max * height)
    cv2_module.rectangle(canvas, (x_min, y_min), (x_max, y_max), color, 2)
    cx = int(item.centroid_x * width)
    cy = int(item.centroid_y * height)
    cv2_module.circle(canvas, (cx, cy), 4, color, -1)
    cv2_module.putText(
        canvas,
        item.track_id,
        (x_min, max(12, y_min - 4)),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        0.4,
        color,
        1,
        cv2_module.LINE_AA,
    )
