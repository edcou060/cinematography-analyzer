"""PyAV extractor: ordered decode, requested vs decoded time, no cross-shot fill."""

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pytest
from numpy.typing import NDArray
from tests.factories import SAMPLE_ID, SHOT_ID

from cine_analyzer.adapters.media.pyav_extract import PyAvSampleExtractor, _encode_jpeg, _rotate
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.media import SamplePurpose, SampleRequest
from cine_analyzer.domain.time import TimeRangeMs
from cine_analyzer.ports.shots import DecodedSample

OTHER_SAMPLE = uuid4()


class _FFmpegError(Exception):
    pass


class _Frame:
    def __init__(
        self,
        *,
        time: object | None = 0.0,
        pts: object | None = None,
        time_base: object | None = None,
        array: NDArray[np.uint8] | None = None,
    ) -> None:
        self.time = time
        self.pts = pts
        self.time_base = time_base
        self._array = np.zeros((8, 8, 3), dtype=np.uint8) if array is None else array

    def to_ndarray(self, *, pixel_format: str = "bgr24") -> NDArray[np.uint8]:
        assert pixel_format == "bgr24"
        return self._array


class _KeywordFrame(_Frame):
    """Matches PyAV's positional ``format=`` argument."""

    def to_ndarray(self, format: str = "bgr24") -> NDArray[np.uint8]:  # noqa: A002
        assert format == "bgr24"
        return self._array


class _Container:
    def __init__(
        self,
        frames: list[_Frame],
        *,
        video_streams: object = ("video",),
        decode_error: Exception | None = None,
    ) -> None:
        self._frames = frames
        self.streams = SimpleNamespace(video=video_streams)
        self._decode_error = decode_error
        self.closed = False

    def decode(self, video: int = 0) -> list[_Frame]:
        assert video == 0
        if self._decode_error is not None:
            raise self._decode_error
        return list(self._frames)

    def close(self) -> None:
        self.closed = True


def _request(
    *,
    sample_id: UUID = SAMPLE_ID,
    shot_id: UUID = SHOT_ID,
    requested_ms: int = 0,
) -> SampleRequest:
    return SampleRequest(
        sample_id=sample_id,
        shot_id=shot_id,
        requested_ms=requested_ms,
        purposes=(SamplePurpose.EVIDENCE,),
    )


def _api(container: _Container | Exception) -> SimpleNamespace:
    def opener(_path: str) -> _Container:
        if isinstance(container, Exception):
            raise container
        return container

    return SimpleNamespace(open=opener, FFmpegError=_FFmpegError)


def test_first_frame_at_or_after_the_request_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _Container(
        [_KeywordFrame(time=0.0), _KeywordFrame(time=0.08), _KeywordFrame(time=0.12)]
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av", lambda: _api(container)
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract._encode_jpeg",
        lambda _frame, **_kwargs: b"jpeg-" + str(_kwargs["rotation_degrees"]).encode(),
    )
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    results = PyAvSampleExtractor().extract(
        source,
        (_request(requested_ms=100),),
        {SHOT_ID: TimeRangeMs(start_ms=0, end_ms=4000)},
        rotation_degrees=0,
    )
    assert results == (
        DecodedSample(
            sample_id=SAMPLE_ID,
            requested_ms=100,
            decoded_ms=120,
            frame_index=2,
            jpeg=b"jpeg-0",
            unavailable_reason=None,
        ),
    )
    assert container.closed is True


def test_a_frame_outside_the_shot_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _Container([_KeywordFrame(time=2.0)])
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av", lambda: _api(container)
    )
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    results = PyAvSampleExtractor().extract(
        source,
        (_request(requested_ms=1500),),
        {SHOT_ID: TimeRangeMs(start_ms=0, end_ms=1000)},
        rotation_degrees=0,
    )
    assert results[0].jpeg is None
    assert results[0].decoded_ms is None
    assert results[0].unavailable_reason == "decoded timestamp is outside the requested shot"


def test_a_request_after_the_last_frame_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _Container([_KeywordFrame(time=0.0)])
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av", lambda: _api(container)
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract._encode_jpeg",
        lambda _frame, **_kwargs: b"jpeg",
    )
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    results = PyAvSampleExtractor().extract(
        source,
        (_request(requested_ms=0), _request(sample_id=OTHER_SAMPLE, requested_ms=9000)),
        {SHOT_ID: TimeRangeMs(start_ms=0, end_ms=10_000)},
        rotation_degrees=0,
    )
    assert results[0].jpeg == b"jpeg"
    assert results[1].unavailable_reason == "no frame at or after the requested timestamp"
    assert [item.sample_id for item in results] == [SAMPLE_ID, OTHER_SAMPLE]


def test_open_and_decode_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    extractor = PyAvSampleExtractor()
    requests = (_request(),)
    ranges = {SHOT_ID: TimeRangeMs(start_ms=0, end_ms=1000)}

    def boom() -> SimpleNamespace:
        raise ImportError("av")

    monkeypatch.setattr("cine_analyzer.adapters.media.pyav_extract.load_av", boom)
    with pytest.raises(AdapterError) as missing:
        extractor.extract(source, requests, ranges, rotation_degrees=0)
    assert missing.value.code == "SHOT_EXTRACT_UNAVAILABLE"

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av",
        lambda: _api(OSError("io")),
    )
    with pytest.raises(AdapterError) as io_error:
        extractor.extract(source, requests, ranges, rotation_degrees=0)
    assert io_error.value.code == "SHOT_EXTRACT_FAILED"

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av",
        lambda: _api(_FFmpegError("bad")),
    )
    with pytest.raises(AdapterError) as ffmpeg:
        extractor.extract(source, requests, ranges, rotation_degrees=0)
    assert ffmpeg.value.code == "SHOT_EXTRACT_FAILED"

    empty = _Container([], video_streams=())
    monkeypatch.setattr("cine_analyzer.adapters.media.pyav_extract.load_av", lambda: _api(empty))
    with pytest.raises(AdapterError) as no_video:
        extractor.extract(source, requests, ranges, rotation_degrees=0)
    assert no_video.value.code == "SHOT_EXTRACT_FAILED"

    broken = _Container([], decode_error=RuntimeError("decode"))
    monkeypatch.setattr("cine_analyzer.adapters.media.pyav_extract.load_av", lambda: _api(broken))
    with pytest.raises(AdapterError) as decode:
        extractor.extract(source, requests, ranges, rotation_degrees=0)
    assert decode.value.code == "SHOT_EXTRACT_FAILED"

    av_decode = _Container([], decode_error=_FFmpegError("mid"))
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av", lambda: _api(av_decode)
    )
    with pytest.raises(AdapterError) as mid:
        extractor.extract(source, requests, ranges, rotation_degrees=0)
    assert mid.value.code == "SHOT_EXTRACT_FAILED"
    assert av_decode.closed is True


def test_frames_without_usable_timestamps_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = [
        _KeywordFrame(time=None, pts=None, time_base=None),
        _KeywordFrame(time="bad"),
        _KeywordFrame(time=-0.1),
        _KeywordFrame(time=None, pts="x", time_base=1),
        _KeywordFrame(time=None, pts=3, time_base=0.04),
    ]
    container = _Container(frames)
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av", lambda: _api(container)
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract._encode_jpeg",
        lambda _frame, **_kwargs: b"ok",
    )
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    results = PyAvSampleExtractor().extract(
        source,
        (_request(requested_ms=100),),
        {SHOT_ID: TimeRangeMs(start_ms=0, end_ms=4000)},
        rotation_degrees=0,
    )
    assert results[0].decoded_ms == 120
    assert results[0].frame_index == 4


def test_encode_jpeg_and_rotation_cover_right_angles() -> None:
    frame = _KeywordFrame(array=np.zeros((4, 6, 3), dtype=np.uint8))
    encoded = _encode_jpeg(frame, rotation_degrees=0)
    assert encoded[:2] == b"\xff\xd8"
    rotated = _rotate(np.zeros((4, 6, 3), dtype=np.uint8), 90)
    assert rotated.shape == (6, 4, 3)
    assert _rotate(np.zeros((4, 6, 3), dtype=np.uint8), 180).shape == (4, 6, 3)
    assert _rotate(np.zeros((4, 6, 3), dtype=np.uint8), 270).shape == (6, 4, 3)
    assert _rotate(np.zeros((4, 6, 3), dtype=np.uint8), 0).shape == (4, 6, 3)


def test_jpeg_encode_failure_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    monkeypatch.setattr(cv2, "imencode", lambda *_args, **_kwargs: (False, None))
    with pytest.raises(AdapterError) as caught:
        _encode_jpeg(_KeywordFrame(), rotation_degrees=0)
    assert caught.value.code == "SHOT_EXTRACT_FAILED"


def test_a_container_without_close_still_returns_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _NoClose:
        streams = SimpleNamespace(video=("video",))

        def decode(self, video: int = 0) -> list[_Frame]:
            assert video == 0
            return []

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.pyav_extract.load_av",
        lambda: SimpleNamespace(open=lambda _path: _NoClose(), FFmpegError=_FFmpegError),
    )
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    results = PyAvSampleExtractor().extract(
        source,
        (_request(requested_ms=10),),
        {SHOT_ID: TimeRangeMs(start_ms=0, end_ms=1000)},
        rotation_degrees=0,
    )
    assert results[0].unavailable_reason == "no frame at or after the requested timestamp"


def test_load_av_imports_the_pinned_api() -> None:
    from cine_analyzer.adapters.media.pyav_extract import load_av

    api = load_av()
    assert callable(api.open)
    assert api.FFmpegError is not None
