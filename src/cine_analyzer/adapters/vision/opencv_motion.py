"""CPU Farneback motion adapter (ADR-0015). No camera-movement labels."""

from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2
from cine_analyzer.domain.config import MotionConfig
from cine_analyzer.domain.spatial import BoxNorm
from cine_analyzer.ports.motion import FlowPairStats, MotionPairInput

__all__ = ["OpenCvMotionAnalyzer"]

_GRAD_MIN = 2.0
_MIN_VALID = 16
_EPS = 1e-9


class OpenCvMotionAnalyzer:
    """Dense flow between two JPEGs. Pairs with no usable texture return None."""

    def analyze_pair(self, pair: MotionPairInput, config: MotionConfig) -> FlowPairStats | None:
        """Farneback global/residual magnitudes, normalized by diagonal and dt."""
        cv2 = load_cv2()
        gray_a = _decode_gray(pair.jpeg_a, config.working_max_side, cv2)
        gray_b = _decode_gray(pair.jpeg_b, config.working_max_side, cv2)
        if gray_a is None or gray_b is None:
            return None
        if gray_a.shape != gray_b.shape:
            return None
        flow = cv2.calcOpticalFlowFarneback(
            gray_a,
            gray_b,
            None,
            config.farneback.pyr_scale,
            config.farneback.levels,
            config.farneback.winsize,
            config.farneback.iterations,
            config.farneback.poly_n,
            config.farneback.poly_sigma,
            0,
        )
        if flow is None:
            return None
        flow_arr = cast("NDArray[np.float32]", np.asarray(flow, dtype=np.float32))
        valid = _valid_mask(gray_a, flow_arr, pair.subject_boxes, cv2)
        total = int(gray_a.size)
        valid_count = int(valid.sum())
        if valid_count < _MIN_VALID or total <= 0:
            return None
        dx = flow_arr[..., 0][valid]
        dy = flow_arr[..., 1][valid]
        global_dx = float(np.median(dx))
        global_dy = float(np.median(dy))
        residual = np.hypot(dx - global_dx, dy - global_dy)
        height, width = gray_a.shape
        diagonal = float(np.hypot(width, height))
        dt_s = max(pair.dt_ms / 1000.0, _EPS)
        scale = diagonal * dt_s
        global_magnitude = float(np.hypot(global_dx, global_dy) / scale)
        residual_median = float(np.median(residual) / scale)
        residual_p90 = float(np.percentile(residual, 90.0) / scale)
        return FlowPairStats(
            sample_id_a=pair.sample_id_a,
            sample_id_b=pair.sample_id_b,
            dt_ms=pair.dt_ms,
            at_ms=pair.at_ms,
            global_dx=global_dx,
            global_dy=global_dy,
            global_magnitude=global_magnitude,
            residual_magnitude_median=residual_median,
            residual_magnitude_p90=residual_p90,
            valid_ratio=min(1.0, max(0.0, valid_count / total)),
            flagged_discontinuity=global_magnitude > config.discontinuity_diag_per_s,
        )


def _decode_gray(jpeg: bytes, max_side: int, cv2: Any) -> NDArray[np.uint8] | None:
    array = np.frombuffer(jpeg, dtype=np.uint8)
    bgr = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    height, width = bgr.shape[:2]
    longest = max(height, width)
    if longest > max_side:
        scale = max_side / longest
        new_w = max(1, round(width * scale))
        new_h = max(1, round(height * scale))
        bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cast("NDArray[np.uint8]", gray)


def _valid_mask(
    gray: NDArray[np.uint8],
    flow: NDArray[np.float32],
    boxes: tuple[BoxNorm, ...],
    cv2: Any,
) -> NDArray[np.bool_]:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    textured = np.hypot(gx, gy) >= _GRAD_MIN
    finite = np.isfinite(flow[..., 0]) & np.isfinite(flow[..., 1])
    valid = textured & finite
    if boxes:
        valid = valid & ~_subject_mask(gray.shape, boxes)
    return cast("NDArray[np.bool_]", valid)


def _subject_mask(shape: tuple[int, ...], boxes: tuple[BoxNorm, ...]) -> NDArray[np.bool_]:
    height, width = int(shape[0]), int(shape[1])
    mask = np.zeros((height, width), dtype=np.bool_)
    for box in boxes:
        y0 = max(0, int(box.y_min * height))
        y1 = min(height, int(np.ceil(box.y_max * height)))
        x0 = max(0, int(box.x_min * width))
        x1 = min(width, int(np.ceil(box.x_max * width)))
        if y1 > y0 and x1 > x0:
            mask[y0:y1, x0:x1] = True
    return mask
