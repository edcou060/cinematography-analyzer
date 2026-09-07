"""Fake detector: scripted hits and magenta-blob probe."""

from uuid import uuid4

import numpy as np
import pytest
from tests.unit.chromatic.jpeg_util import encode_jpeg, solid_rgb
from tests.unit.spatial.helpers import box, gray_frame, hit, magenta_frame, spatial_config

from cine_analyzer.adapters.vision.fake_subject import FakeSubjectDetector
from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2
from cine_analyzer.ports.spatial import SpatialFrame


def test_scripted_hits_are_returned_for_known_sample_ids() -> None:
    sample = uuid4()
    scripted = hit(sample, box(0.1, 0.1, 0.4, 0.8))
    detector = FakeSubjectDetector({sample: (scripted,)})
    found = detector.infer((gray_frame(sample),), spatial_config())
    assert found == (scripted,)


def test_an_empty_script_skips_the_magenta_probe() -> None:
    sample = uuid4()
    detector = FakeSubjectDetector({sample: ()})
    found = detector.infer((magenta_frame(sample),), spatial_config())
    assert found == ()


def test_magenta_blob_yields_a_person_box() -> None:
    sample = uuid4()
    found = FakeSubjectDetector().infer((magenta_frame(sample),), spatial_config())
    assert len(found) == 1
    assert found[0].class_name == "person"
    assert found[0].sample_id == sample
    height = found[0].box.y_max - found[0].box.y_min
    assert 0.38 < height < 0.62


def test_gray_frames_yield_no_hits() -> None:
    found = FakeSubjectDetector().infer((gray_frame(),), spatial_config())
    assert found == ()


def test_undecodable_jpegs_yield_no_hits() -> None:
    frame = SpatialFrame(sample_id=uuid4(), jpeg=b"not-a-jpeg")
    found = FakeSubjectDetector().infer((frame,), spatial_config())
    assert found == ()


def test_too_few_magenta_pixels_are_ignored() -> None:
    rgb = solid_rgb((64, 64, 64), size=32)
    rgb[4, 4] = (255, 0, 255)
    frame = SpatialFrame(sample_id=uuid4(), jpeg=encode_jpeg(rgb))
    found = FakeSubjectDetector().infer((frame,), spatial_config())
    assert found == ()


def test_non_rgb_and_empty_decodes_yield_no_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()
    sample = uuid4()
    frame = magenta_frame(sample)

    class _Gray:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 8), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_chromatics.load_cv2", _Gray)
    assert FakeSubjectDetector().infer((frame,), spatial_config()) == ()

    class _Empty:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((0, 0, 3), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_chromatics.load_cv2", _Empty)
    assert FakeSubjectDetector().infer((frame,), spatial_config()) == ()

    class _ZeroWidth:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 0, 3), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_chromatics.load_cv2", _ZeroWidth)
    assert FakeSubjectDetector().infer((frame,), spatial_config()) == ()


def test_four_channel_decodes_yield_no_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()

    class _Bgra:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 8, 4), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_chromatics.load_cv2", _Bgra)
    assert FakeSubjectDetector().infer((magenta_frame(),), spatial_config()) == ()


def test_degenerate_blob_bounds_yield_no_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()

    class _OddXs:
        size = 12

        def min(self) -> int:
            return 10

        def max(self) -> int:
            return 0

    class _Ys:
        size = 12

        def min(self) -> int:
            return 0

        def max(self) -> int:
            return 4

    class _Api:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 8, 3), dtype=np.uint8)

        def cvtColor(self, image: np.ndarray, _code: object) -> np.ndarray:  # noqa: N802
            return image

        def inRange(self, _hsv: object, _lower: object, _upper: object) -> np.ndarray:  # noqa: N802
            return np.ones((8, 8), dtype=np.uint8)

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.opencv_chromatics.load_cv2",
        _Api,
    )
    monkeypatch.setattr(
        "numpy.where",
        lambda _mask: (_Ys(), _OddXs()),
    )
    assert FakeSubjectDetector().infer((magenta_frame(),), spatial_config()) == ()
