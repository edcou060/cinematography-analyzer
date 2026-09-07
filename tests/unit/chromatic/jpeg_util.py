"""Encode tiny RGB arrays as JPEG bytes for chromatic tests."""

import numpy as np
from numpy.typing import NDArray

from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2


def encode_jpeg(rgb: NDArray[np.uint8], *, quality: int = 100) -> bytes:
    """Encode HxWx3 uint8 sRGB as JPEG."""
    cv2 = load_cv2()
    ok, buffer = cv2.imencode(
        ".jpg",
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        [int(cv2.IMWRITE_JPEG_QUALITY), quality],
    )
    if not ok:
        message = "jpeg encode failed"
        raise RuntimeError(message)
    return bytes(buffer.tobytes())


def solid_rgb(color: tuple[int, int, int], *, size: int = 32) -> NDArray[np.uint8]:
    frame = np.zeros((size, size, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame
