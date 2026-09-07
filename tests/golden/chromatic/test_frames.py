"""Golden chromatic frames: palette order, letterbox, lighting-key estimates."""

from uuid import uuid4

import numpy as np
import pytest
from tests.unit.chromatic.jpeg_util import encode_jpeg, solid_rgb

from cine_analyzer.adapters.vision.opencv_chromatics import OpenCvChromaticAnalyzer
from cine_analyzer.domain.chromatics import LightingKeyLabel
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.chromatics import ChromaticFrame

TOLERANCE_PROPORTION = 0.12
TOLERANCE_LSTAR = 2.0


def _analyze(rgb: np.ndarray) -> object:
    frame = ChromaticFrame(sample_id=uuid4(), jpeg=encode_jpeg(rgb))
    return OpenCvChromaticAnalyzer().analyze_shot((frame,), AnalysisConfig().chromatic)


def _mixture() -> np.ndarray:
    rgb = np.zeros((50, 50, 3), dtype=np.uint8)
    rgb[:, :] = (220, 30, 30)
    rgb[:, 40:] = (30, 30, 220)
    return rgb


def _gradient() -> np.ndarray:
    row = np.linspace(0, 255, 128, dtype=np.uint8)
    plane = np.tile(row, (48, 1))
    return np.stack([plane, plane, plane], axis=2)


def _letterboxed() -> np.ndarray:
    rgb = np.zeros((60, 80, 3), dtype=np.uint8)
    rgb[10:50, :, :] = (20, 180, 40)
    return rgb


def _three_colours() -> np.ndarray:
    rgb = np.zeros((48, 144, 3), dtype=np.uint8)
    rgb[:, :48] = (200, 20, 20)
    rgb[:, 48:96] = (20, 200, 20)
    rgb[:, 96:] = (20, 20, 200)
    return rgb


@pytest.mark.parametrize(
    ("name", "rgb"),
    [
        ("solid_white", solid_rgb((255, 255, 255), size=48)),
        ("solid_red", solid_rgb((220, 20, 20), size=48)),
        ("mix_80_20", _mixture()),
        ("gradient", _gradient()),
        ("letterboxed", _letterboxed()),
        ("three_colours", _three_colours()),
    ],
)
def test_golden_frames_are_deterministic(name: str, rgb: np.ndarray) -> None:
    first = _analyze(rgb)
    second = _analyze(rgb)
    assert first.status is MetricStatus.OK  # type: ignore[union-attr]
    assert first.value is not None  # type: ignore[union-attr]
    assert second.value is not None  # type: ignore[union-attr]
    assert first.value.lighting_key is second.value.lighting_key
    assert [swatch.rgb.hex for swatch in first.value.palette] == [
        swatch.rgb.hex for swatch in second.value.palette
    ]
    assert first.value.lightness.p50_lstar == pytest.approx(
        second.value.lightness.p50_lstar, abs=TOLERANCE_LSTAR
    )
    assert name


def test_letterboxed_golden_is_not_a_black_palette() -> None:
    result = _analyze(_letterboxed())
    assert result.status is MetricStatus.OK  # type: ignore[union-attr]
    assert result.value is not None  # type: ignore[union-attr]
    dominant = result.value.palette[0]
    assert dominant.rgb.g > 80
    assert dominant.lab.lstar > 25.0
    assert result.value.usable_pixel_ratio == pytest.approx(40 / 60, abs=0.05)


def test_mixture_golden_orders_red_before_blue() -> None:
    result = _analyze(_mixture())
    assert result.value is not None  # type: ignore[union-attr]
    assert result.value.palette[0].proportion == pytest.approx(0.8, abs=TOLERANCE_PROPORTION)
    assert result.value.palette[0].rgb.r > result.value.palette[0].rgb.b


def test_white_golden_is_high_key_estimate() -> None:
    result = _analyze(solid_rgb((255, 255, 255), size=48))
    assert result.value is not None  # type: ignore[union-attr]
    assert result.value.lighting_key is LightingKeyLabel.HIGH_KEY_ESTIMATE
    assert "ESTIMATE" in result.value.lighting_key.value


def test_three_colour_golden_has_fewer_than_five_swatches() -> None:
    config = AnalysisConfig().chromatic.model_copy(update={"delta_e_merge": 12.0})
    frame = ChromaticFrame(sample_id=uuid4(), jpeg=encode_jpeg(_three_colours()))
    result = OpenCvChromaticAnalyzer().analyze_shot((frame,), config)
    assert result.value is not None
    assert 1 <= len(result.value.palette) < 5
