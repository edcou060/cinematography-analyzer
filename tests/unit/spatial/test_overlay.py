"""Evidence overlays copy the JPEG and draw guides without mutating source bytes."""

from uuid import uuid4

import numpy as np
import pytest
from tests.unit.chromatic.jpeg_util import encode_jpeg, solid_rgb
from tests.unit.spatial.helpers import box

from cine_analyzer.adapters.vision.opencv_chromatics import load_cv2
from cine_analyzer.adapters.vision.opencv_overlay import OpenCvOverlayRenderer
from cine_analyzer.domain.spatial import SubjectObservation


def _observation(track_id: str, *, y_min: float = 0.2) -> SubjectObservation:
    return SubjectObservation(
        track_id=track_id,
        sample_id=uuid4(),
        class_name="person",
        detector_confidence=0.9,
        box=box(0.2, y_min, 0.5, y_min + 0.4),
        centroid_x=0.35,
        centroid_y=y_min + 0.2,
    )


def test_overlay_is_a_new_jpeg() -> None:
    source = encode_jpeg(solid_rgb((40, 40, 40), size=48))
    rendered = OpenCvOverlayRenderer().render(
        source,
        (_observation("t0001"), _observation("t0002")),
        "t0001",
    )
    assert rendered is not None
    assert rendered[:2] == b"\xff\xd8"
    assert rendered != source


def test_undecodable_source_returns_none() -> None:
    renderer = OpenCvOverlayRenderer()
    assert renderer.render(b"", (), None) is None
    assert renderer.render(b"not-a-jpeg", (), None) is None


def test_non_rgb_and_four_channel_decodes_return_none(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()
    source = encode_jpeg(solid_rgb((10, 10, 10), size=16))

    class _Gray:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 8), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_overlay.load_cv2", _Gray)
    assert OpenCvOverlayRenderer().render(source, (), None) is None

    class _Bgra:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 8, 4), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_overlay.load_cv2", _Bgra)
    assert OpenCvOverlayRenderer().render(source, (), None) is None


def test_empty_decodes_return_none(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()
    source = encode_jpeg(solid_rgb((10, 10, 10), size=16))

    class _Empty:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((0, 0, 3), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_overlay.load_cv2", _Empty)
    assert OpenCvOverlayRenderer().render(source, (), None) is None

    class _ZeroWidth:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imdecode(self, _array: object, _flags: object) -> np.ndarray:
            return np.zeros((8, 0, 3), dtype=np.uint8)

    monkeypatch.setattr("cine_analyzer.adapters.vision.opencv_overlay.load_cv2", _ZeroWidth)
    assert OpenCvOverlayRenderer().render(source, (), None) is None


def test_encode_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    real = load_cv2()
    source = encode_jpeg(solid_rgb((10, 10, 10), size=16))

    class _Fail:
        def __getattr__(self, name: str) -> object:
            return getattr(real, name)

        def imencode(self, *_args: object, **_kwargs: object) -> tuple[bool, None]:
            return False, None

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.opencv_overlay.load_cv2",
        _Fail,
    )
    assert OpenCvOverlayRenderer().render(source, (), None) is None


def test_a_box_near_the_top_still_draws() -> None:
    source = encode_jpeg(solid_rgb((20, 20, 20), size=32))
    rendered = OpenCvOverlayRenderer().render(source, (_observation("t0001", y_min=0.0),), "t0001")
    assert rendered is not None
    assert rendered[:2] == b"\xff\xd8"
