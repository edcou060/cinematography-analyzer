"""Float CIE Lab conversion: L* is not an 8-bit OpenCV channel."""

import numpy as np
import pytest

from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2, load_sklearn, rgb_uint8_to_lab


def test_black_maps_to_zero_lstar() -> None:
    rgb = np.zeros((1, 1, 3), dtype=np.uint8)
    lab = rgb_uint8_to_lab(rgb)
    assert lab[0, 0, 0] == pytest.approx(0.0, abs=0.75)
    assert lab[0, 0, 1] == pytest.approx(0.0, abs=1.0)
    assert lab[0, 0, 2] == pytest.approx(0.0, abs=1.0)


def test_white_maps_to_one_hundred_lstar() -> None:
    rgb = np.full((1, 1, 3), 255, dtype=np.uint8)
    lab = rgb_uint8_to_lab(rgb)
    assert lab[0, 0, 0] == pytest.approx(100.0, abs=0.75)


def test_srgb_red_has_cie_style_lab() -> None:
    rgb = np.zeros((1, 1, 3), dtype=np.uint8)
    rgb[0, 0] = (255, 0, 0)
    lab = rgb_uint8_to_lab(rgb)[0, 0]
    assert 50.0 < float(lab[0]) < 60.0
    assert float(lab[1]) > 60.0
    assert float(lab[2]) > 40.0


def test_lstar_stays_within_cie_range_for_a_ramp() -> None:
    ramp = np.stack(
        [np.full((1, 256, 3), fill, dtype=np.uint8) for fill in range(256)],
        axis=0,
    ).reshape(256, 256, 3)
    lab = rgb_uint8_to_lab(ramp)
    assert float(lab[:, :, 0].min()) >= -0.05
    assert float(lab[:, :, 0].max()) <= 100.05


def test_rgb_uint8_to_lab_accepts_an_injected_cv2_module() -> None:
    cv2 = load_cv2()
    rgb = np.full((1, 1, 3), 255, dtype=np.uint8)
    lab = rgb_uint8_to_lab(rgb, cv2)
    assert lab[0, 0, 0] == pytest.approx(100.0, abs=0.75)


def test_load_cv2_and_sklearn_return_the_real_libraries() -> None:
    cv2 = load_cv2()
    sklearn = load_sklearn()
    assert cv2.COLOR_RGB2LAB is not None
    assert sklearn.MiniBatchKMeans is not None
