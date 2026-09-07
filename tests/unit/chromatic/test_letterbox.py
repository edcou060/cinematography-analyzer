"""Border-connected letterbox masking and usable-pixel ratio."""

import numpy as np
import pytest
from tests.unit.chromatic.jpeg_util import solid_rgb

from cine_analyzer.adapters.vision.opencv_chromatics import letterbox_mask, rgb_uint8_to_lab


def test_a_full_frame_has_usable_ratio_one() -> None:
    lab = rgb_uint8_to_lab(solid_rgb((0, 170, 0), size=16))
    mask, ratio = letterbox_mask(lab[:, :, 0], lstar_max=8.0, coverage=0.92)
    assert ratio == 1.0
    assert bool(mask.all())


def test_black_bars_touching_the_border_are_masked() -> None:
    frame = np.zeros((60, 80, 3), dtype=np.uint8)
    frame[10:50, :, :] = (0, 170, 0)
    lab = rgb_uint8_to_lab(frame)
    mask, ratio = letterbox_mask(lab[:, :, 0], lstar_max=8.0, coverage=0.92)
    assert ratio == pytest.approx(40 / 60, abs=0.02)
    assert not bool(mask[:10].any())
    assert not bool(mask[50:].any())
    assert bool(mask[10:50].all())


def test_an_all_black_frame_has_no_usable_pixels() -> None:
    lab = rgb_uint8_to_lab(solid_rgb((0, 0, 0), size=12))
    mask, ratio = letterbox_mask(lab[:, :, 0], lstar_max=8.0, coverage=0.92)
    assert ratio == 0.0
    assert not bool(mask.any())


def test_side_bars_touching_the_border_are_masked() -> None:
    frame = np.zeros((40, 80, 3), dtype=np.uint8)
    frame[:, 10:70] = (0, 170, 0)
    lab = rgb_uint8_to_lab(frame)
    mask, ratio = letterbox_mask(lab[:, :, 0], lstar_max=8.0, coverage=0.92)
    assert ratio == pytest.approx(60 / 80, abs=0.03)
    assert not bool(mask[:, :10].any())
    assert not bool(mask[:, 70:].any())


def test_interior_black_that_does_not_touch_the_border_is_kept() -> None:
    frame = np.full((20, 20, 3), 200, dtype=np.uint8)
    frame[8:12, 8:12] = 0
    lab = rgb_uint8_to_lab(frame)
    _mask, ratio = letterbox_mask(lab[:, :, 0], lstar_max=8.0, coverage=0.92)
    assert ratio == 1.0


def test_an_empty_lstar_plane_has_usable_ratio_zero() -> None:
    empty = np.zeros((0, 0), dtype=np.float32)
    mask, ratio = letterbox_mask(empty, lstar_max=8.0, coverage=0.92)
    assert ratio == 0.0
    assert mask.size == 0
