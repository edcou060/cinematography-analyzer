"""Farneback adapter: global vs residual, subject masks, decode failures."""

from uuid import uuid4

import numpy as np
import pytest
from tests.unit.chromatic.jpeg_util import encode_jpeg

from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2
from cine_analyzer.adapters.vision.opencv_motion import OpenCvMotionAnalyzer, _subject_mask
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.spatial import BoxNorm
from cine_analyzer.ports.motion import MotionPairInput


def _pair(jpeg_a: bytes, jpeg_b: bytes, *, boxes: tuple[BoxNorm, ...] = ()) -> MotionPairInput:
    return MotionPairInput(
        sample_id_a=uuid4(),
        sample_id_b=uuid4(),
        jpeg_a=jpeg_a,
        jpeg_b=jpeg_b,
        dt_ms=160,
        at_ms=80,
        subject_boxes=boxes,
    )


def _texture(*, shift_x: int = 0, box_x: int | None = None, size: int = 64) -> np.ndarray:
    xs = np.arange(size, dtype=np.float64) + shift_x
    wave = (127 + 90 * np.sin(2 * np.pi * xs / 16.0)).astype(np.uint8)
    frame = np.broadcast_to(wave[None, :, None], (size, size, 3)).copy()
    ywave = (127 + 40 * np.sin(2 * np.pi * np.arange(size) / 12.0)).astype(np.uint8)
    frame = ((frame.astype(np.int16) + ywave[:, None, None]) // 2).astype(np.uint8)
    if box_x is not None:
        width = size // 4
        frame[size // 4 : 3 * size // 4, box_x : box_x + width] = (255, 220, 0)
    return frame


def test_translated_background_has_higher_global_than_residual() -> None:
    analyzer = OpenCvMotionAnalyzer()
    config = AnalysisConfig().motion
    first = encode_jpeg(_texture())
    second = encode_jpeg(_texture(shift_x=5))
    stats = analyzer.analyze_pair(_pair(first, second), config)
    assert stats is not None
    assert stats.global_magnitude > stats.residual_magnitude_median
    assert 0.0 <= stats.valid_ratio <= 1.0
    assert stats.flagged_discontinuity is False


def test_moving_object_has_higher_residual_than_a_static_pair() -> None:
    analyzer = OpenCvMotionAnalyzer()
    config = AnalysisConfig().motion
    static = analyzer.analyze_pair(
        _pair(encode_jpeg(_texture(box_x=12)), encode_jpeg(_texture(box_x=12))),
        config,
    )
    moving = analyzer.analyze_pair(
        _pair(encode_jpeg(_texture(box_x=8)), encode_jpeg(_texture(box_x=28))),
        config,
    )
    assert static is not None
    assert moving is not None
    assert moving.residual_magnitude_median > static.residual_magnitude_median


def test_invalid_jpeg_returns_none() -> None:
    analyzer = OpenCvMotionAnalyzer()
    assert analyzer.analyze_pair(_pair(b"not-jpeg", b"not-jpeg"), AnalysisConfig().motion) is None


def test_mismatched_shapes_return_none() -> None:
    analyzer = OpenCvMotionAnalyzer()
    tall = encode_jpeg(np.full((80, 32, 3), 80, dtype=np.uint8))
    wide = encode_jpeg(np.full((32, 80, 3), 80, dtype=np.uint8))
    assert analyzer.analyze_pair(_pair(tall, wide), AnalysisConfig().motion) is None


def test_subject_mask_does_not_require_boxes_to_run() -> None:
    analyzer = OpenCvMotionAnalyzer()
    config = AnalysisConfig().motion
    first = encode_jpeg(_texture())
    second = encode_jpeg(_texture(shift_x=3))
    boxed = analyzer.analyze_pair(
        _pair(first, second, boxes=(BoxNorm(x_min=0.0, y_min=0.0, x_max=0.2, y_max=0.2),)),
        config,
    )
    plain = analyzer.analyze_pair(_pair(first, second), config)
    assert boxed is not None
    assert plain is not None


def test_discontinuity_flag_fires_on_a_hard_cut() -> None:
    analyzer = OpenCvMotionAnalyzer()
    config = AnalysisConfig().motion.model_copy(update={"discontinuity_diag_per_s": 0.01})
    left = encode_jpeg(_texture())
    right = encode_jpeg(_texture(shift_x=6))
    stats = analyzer.analyze_pair(_pair(left, right), config)
    assert stats is not None
    assert stats.global_magnitude > config.discontinuity_diag_per_s
    assert stats.flagged_discontinuity is True


def test_frames_larger_than_working_max_side_are_downscaled() -> None:
    analyzer = OpenCvMotionAnalyzer()
    config = AnalysisConfig().motion
    large = _texture(size=400)
    shifted = _texture(size=400, shift_x=8)
    stats = analyzer.analyze_pair(_pair(encode_jpeg(large), encode_jpeg(shifted)), config)
    assert stats is not None
    assert stats.global_magnitude > 0.0


def test_subject_mask_skips_a_zero_area_canvas() -> None:
    box = BoxNorm(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0)
    mask = _subject_mask((0, 8), (box,))
    assert mask.shape == (0, 8)
    assert not mask.any()


def test_one_invalid_jpeg_returns_none() -> None:
    analyzer = OpenCvMotionAnalyzer()
    valid = encode_jpeg(_texture())
    assert analyzer.analyze_pair(_pair(valid, b"nope"), AnalysisConfig().motion) is None


def test_untextured_frames_return_none() -> None:
    analyzer = OpenCvMotionAnalyzer()
    solid = encode_jpeg(np.full((32, 32, 3), 8, dtype=np.uint8))
    assert analyzer.analyze_pair(_pair(solid, solid), AnalysisConfig().motion) is None


def test_farneback_none_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    cv2 = load_cv2()

    class _Wrap:
        def __getattr__(self, name: str) -> object:
            return getattr(cv2, name)

        def calcOpticalFlowFarneback(  # noqa: N802
            self, *args: object, **kwargs: object
        ) -> None:
            assert args or kwargs

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_motion.load_cv2", _Wrap)
    analyzer = OpenCvMotionAnalyzer()
    jpeg = encode_jpeg(_texture())
    assert analyzer.analyze_pair(_pair(jpeg, jpeg), AnalysisConfig().motion) is None
