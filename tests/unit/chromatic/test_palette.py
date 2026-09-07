"""Palette prevalence order, clustering, and lighting labels from JPEGs."""

from uuid import uuid4

import numpy as np
import pytest
from tests.unit.chromatic.jpeg_util import encode_jpeg, solid_rgb

from cine_analyzer.adapters.vision.opencv_chromatics import (
    OpenCvChromaticAnalyzer,
    _merge_centres,
    _merge_duplicate_hex,
    _palette,
    _swatch,
    load_cv2,
)
from cine_analyzer.domain.chromatics import ColorSwatch, LabColor, LightingKeyLabel, RgbColor
from cine_analyzer.domain.config import AnalysisConfig, ChromaticConfig
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.chromatics import ChromaticFrame


def _frame(rgb: np.ndarray) -> ChromaticFrame:
    return ChromaticFrame(sample_id=uuid4(), jpeg=encode_jpeg(rgb))


def _config(**overrides: object) -> ChromaticConfig:
    chromatic = AnalysisConfig().chromatic
    if not overrides:
        return chromatic
    return chromatic.model_copy(update=overrides)


def test_empty_frames_are_insufficient() -> None:
    result = OpenCvChromaticAnalyzer().analyze_shot((), _config())
    assert result.status is MetricStatus.INSUFFICIENT_DATA
    assert result.reason_code == "chromatic_no_decoded_samples"
    assert result.value is None


def test_undecodable_bytes_are_failed() -> None:
    frames = (ChromaticFrame(sample_id=uuid4(), jpeg=b"not-a-jpeg"),)
    result = OpenCvChromaticAnalyzer().analyze_shot(frames, _config())
    assert result.status is MetricStatus.FAILED
    assert result.reason_code == "chromatic_decode_failed"


def test_empty_jpeg_bytes_are_failed() -> None:
    frames = (ChromaticFrame(sample_id=uuid4(), jpeg=b""),)
    result = OpenCvChromaticAnalyzer().analyze_shot(frames, _config())
    assert result.status is MetricStatus.FAILED
    assert result.reason_code == "chromatic_decode_failed"


def test_solid_black_is_a_low_key_estimate() -> None:
    result = OpenCvChromaticAnalyzer().analyze_shot((_frame(solid_rgb((0, 0, 0))),), _config())
    # Pure black is fully letterboxed, so the analyzer abstains rather than
    # letting a black cluster dominate a "palette".
    assert result.status is MetricStatus.INSUFFICIENT_DATA
    assert result.reason_code == "chromatic_letterbox_insufficient"


def test_solid_white_is_a_high_key_estimate() -> None:
    white = _frame(solid_rgb((255, 255, 255)))
    result = OpenCvChromaticAnalyzer().analyze_shot((white,), _config())
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert result.value.lighting_key is LightingKeyLabel.HIGH_KEY_ESTIMATE
    assert len(result.value.palette) == 1
    assert result.value.palette[0].proportion == pytest.approx(1.0)
    assert result.value.palette[0].rgb.hex.startswith("#F")


def test_solid_red_palette_is_prevalence_one() -> None:
    result = OpenCvChromaticAnalyzer().analyze_shot((_frame(solid_rgb((220, 20, 20))),), _config())
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert result.value.palette[0].rgb.r > result.value.palette[0].rgb.b
    assert result.value.usable_pixel_ratio == pytest.approx(1.0)


def test_eighty_twenty_mixture_orders_by_prevalence() -> None:
    rgb = np.zeros((50, 50, 3), dtype=np.uint8)
    rgb[:, :] = (220, 30, 30)
    rgb[:, 40:] = (30, 30, 220)
    first = OpenCvChromaticAnalyzer().analyze_shot((_frame(rgb),), _config())
    second = OpenCvChromaticAnalyzer().analyze_shot((_frame(rgb),), _config())
    assert first.status is MetricStatus.OK
    assert first.value is not None
    assert second.value is not None
    assert first.value.palette[0].rgb.hex == second.value.palette[0].rgb.hex
    assert first.value.palette[0].proportion >= first.value.palette[1].proportion
    assert first.value.palette[0].rgb.r > first.value.palette[0].rgb.b
    assert first.value.palette[0].proportion == pytest.approx(0.8, abs=0.12)


def test_letterboxed_green_is_not_dominated_by_black_bars() -> None:
    rgb = np.zeros((60, 80, 3), dtype=np.uint8)
    rgb[10:50, :, :] = (20, 180, 20)
    result = OpenCvChromaticAnalyzer().analyze_shot((_frame(rgb),), _config())
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert result.value.usable_pixel_ratio == pytest.approx(40 / 60, abs=0.05)
    dominant = result.value.palette[0]
    assert dominant.rgb.g > dominant.rgb.r
    assert dominant.rgb.g > 80
    assert dominant.lab.lstar > 20.0


def test_three_colour_blocks_yield_fewer_than_five_swatches() -> None:
    rgb = np.zeros((40, 120, 3), dtype=np.uint8)
    rgb[:, :40] = (200, 20, 20)
    rgb[:, 40:80] = (20, 200, 20)
    rgb[:, 80:] = (20, 20, 200)
    config = _config(delta_e_merge=10.0)
    result = OpenCvChromaticAnalyzer().analyze_shot((_frame(rgb),), config)
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert 1 <= len(result.value.palette) <= 5
    assert len(result.value.palette) < 5


def test_downscale_and_pixel_cap_still_return_ok() -> None:
    rgb = solid_rgb((40, 80, 160), size=120)
    config = _config(working_max_side=32, max_pixels_per_shot=80)
    result = OpenCvChromaticAnalyzer().analyze_shot((_frame(rgb),), config)
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert result.value.palette[0].rgb.b > result.value.palette[0].rgb.r


def test_cluster_failure_is_a_failed_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.opencv_chromatics._palette",
        lambda *_args, **_kwargs: (),
    )
    result = OpenCvChromaticAnalyzer().analyze_shot(
        (_frame(solid_rgb((200, 40, 40))),),
        _config(),
    )
    assert result.status is MetricStatus.FAILED
    assert result.reason_code == "chromatic_cluster_failed"


def test_two_runs_match_within_tolerance() -> None:
    rgb = np.linspace(0, 255, 64, dtype=np.uint8)
    frame = np.stack([np.tile(rgb, (64, 1))] * 3, axis=2)
    analyzer = OpenCvChromaticAnalyzer()
    config = _config()
    first = analyzer.analyze_shot((_frame(frame),), config)
    second = analyzer.analyze_shot((_frame(frame),), config)
    assert first.value is not None
    assert second.value is not None
    assert first.value.lighting_key is second.value.lighting_key
    assert [swatch.rgb.hex for swatch in first.value.palette] == [
        swatch.rgb.hex for swatch in second.value.palette
    ]
    assert first.value.lightness.p50_lstar == pytest.approx(
        second.value.lightness.p50_lstar, abs=0.05
    )


def test_a_junk_frame_is_skipped_when_another_decodes() -> None:
    good = _frame(solid_rgb((20, 180, 20)))
    bad = ChromaticFrame(sample_id=uuid4(), jpeg=b"not-a-jpeg")
    result = OpenCvChromaticAnalyzer().analyze_shot((bad, good), _config())
    assert result.status is MetricStatus.OK
    assert result.evidence_sample_ids == (good.sample_id,)


def test_solid_black_with_zero_usable_floor_is_no_pixels() -> None:
    result = OpenCvChromaticAnalyzer().analyze_shot(
        (_frame(solid_rgb((0, 0, 0))),),
        _config(min_usable_pixel_ratio=0.0),
    )
    assert result.status is MetricStatus.INSUFFICIENT_DATA
    assert result.reason_code == "chromatic_no_usable_pixels"


def test_a_zero_size_decoded_frame_is_letterbox_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.opencv_chromatics._decode_jpeg_rgb",
        lambda _jpeg, _cv2: np.zeros((0, 0, 3), dtype=np.uint8),
    )
    result = OpenCvChromaticAnalyzer().analyze_shot(
        (ChromaticFrame(sample_id=uuid4(), jpeg=b"x"),),
        _config(),
    )
    assert result.status is MetricStatus.INSUFFICIENT_DATA
    assert result.reason_code == "chromatic_letterbox_insufficient"


def test_non_rgb_decodes_are_treated_as_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()

    class _Gray:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 8), dtype=np.uint8)

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.opencv_chromatics.load_cv2",
        _Gray,
    )
    result = OpenCvChromaticAnalyzer().analyze_shot(
        (ChromaticFrame(sample_id=uuid4(), jpeg=b"\xff\xd8x"),),
        _config(),
    )
    assert result.status is MetricStatus.FAILED
    assert result.reason_code == "chromatic_decode_failed"


def test_four_channel_decodes_are_treated_as_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()

    class _Bgra:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 8, 4), dtype=np.uint8)

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.opencv_chromatics.load_cv2",
        _Bgra,
    )
    result = OpenCvChromaticAnalyzer().analyze_shot(
        (ChromaticFrame(sample_id=uuid4(), jpeg=b"\xff\xd8x"),),
        _config(),
    )
    assert result.status is MetricStatus.FAILED
    assert result.reason_code == "chromatic_decode_failed"


def test_one_cluster_uses_the_mean_centre() -> None:
    result = OpenCvChromaticAnalyzer().analyze_shot(
        (_frame(solid_rgb((40, 80, 160))),),
        _config(clusters=1),
    )
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert len(result.value.palette) == 1


def test_tiny_swatches_are_dropped_and_the_dominant_is_kept() -> None:
    rgb = np.zeros((50, 50, 3), dtype=np.uint8)
    rgb[:, :] = (220, 30, 30)
    rgb[:, 40:] = (30, 30, 220)
    result = OpenCvChromaticAnalyzer().analyze_shot(
        (_frame(rgb),),
        _config(min_swatch_proportion=1.0),
    )
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert len(result.value.palette) == 1
    assert result.value.palette[0].proportion == pytest.approx(1.0)


def test_empty_lab_pixels_yield_no_swatches() -> None:
    empty = np.zeros((0, 3), dtype=np.float32)
    assert _palette(empty, _config(), load_cv2()) == ()


def test_zero_membership_clusters_yield_no_swatches(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fit(
        _pixels: np.ndarray, cluster_count: int, _config: object
    ) -> tuple[list[np.ndarray], list[int]]:
        centres = [np.array([50.0, 0.0, 0.0], dtype=np.float64) for _ in range(cluster_count)]
        return centres, [0] * cluster_count

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.opencv_chromatics._fit_kmeans",
        fake_fit,
    )
    rgb = np.zeros((20, 40, 3), dtype=np.uint8)
    rgb[:, :20] = (200, 20, 20)
    rgb[:, 20:] = (20, 20, 200)
    result = OpenCvChromaticAnalyzer().analyze_shot((_frame(rgb),), _config())
    assert result.status is MetricStatus.FAILED
    assert result.reason_code == "chromatic_cluster_failed"


def test_close_lab_centres_merge_by_delta_e() -> None:
    near_a = np.array([50.0, 1.0, 0.0], dtype=np.float64)
    near_b = np.array([50.4, 1.1, 0.2], dtype=np.float64)
    far = np.array([20.0, 40.0, 30.0], dtype=np.float64)
    merged = _merge_centres([near_a, near_b, far], [12, 4, 9], 3.0)
    assert len(merged) == 2
    counts = sorted(count for _centre, count in merged)
    assert counts == [9, 16]


def test_duplicate_hex_swatches_merge_and_keep_the_heavier_centre() -> None:
    light = ColorSwatch(
        rank=1,
        lab=LabColor(lstar=40.0, a=10.0, b=10.0),
        rgb=RgbColor(r=200, g=10, b=10, hex="#C80A0A"),
        proportion=1.0,
    )
    heavy = ColorSwatch(
        rank=1,
        lab=LabColor(lstar=55.0, a=12.0, b=8.0),
        rgb=RgbColor(r=200, g=10, b=10, hex="#C80A0A"),
        proportion=1.0,
    )
    merged = _merge_duplicate_hex([(light, 3), (heavy, 7)])
    assert len(merged) == 1
    keeper, count = merged[0]
    assert count == 10
    assert keeper.lab.lstar == 55.0
    tied = _merge_duplicate_hex([(light, 4), (heavy, 4)])
    assert tied[0][0].lab.lstar == 40.0


def test_lab_centres_are_clipped_before_swatch_construction() -> None:
    draft, count = _swatch(np.array([200.0, 200.0, -200.0], dtype=np.float64), 3, load_cv2())
    assert count == 3
    assert draft.lab.lstar == 100.0
    assert draft.lab.a == 127.0
    assert draft.lab.b == -128.0
    assert draft.rgb.hex.startswith("#")
