"""PySceneDetect adapter translates library intervals and refuses unknown detectors."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from cine_analyzer.adapters.vision.pyscenedetect import PySceneDetectShotDetector
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.config import ShotsConfig
from cine_analyzer.domain.shots import TransitionKind


def _config(**overrides: object) -> ShotsConfig:
    payload: dict[str, object] = {
        "backend": "pyscenedetect",
        "detector": "adaptive",
        "min_shot_ms": 300,
    }
    payload.update(overrides)
    return ShotsConfig.model_validate(payload)


class _Timecode:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def get_seconds(self) -> float:
        return self.seconds


class _LegacyStamp:
    def get_seconds(self) -> float:
        return 2.0


class _VideoOpenError(Exception):
    pass


class _Manager:
    def __init__(
        self,
        *,
        intervals: object,
        detect_error: Exception | None = None,
        stats_manager: object | None = None,
    ) -> None:
        self.intervals = intervals
        self.detect_error = detect_error
        self.stats_manager = stats_manager
        self.auto_downscale = True
        self.downscale = 1
        self.detectors: list[object] = []
        self.progress: object = None

    def add_detector(self, detector: object) -> None:
        self.detectors.append(detector)

    def detect_scenes(self, _video: object, **kwargs: object) -> int:
        self.progress = kwargs.get("show_progress")
        if self.detect_error is not None:
            raise self.detect_error
        return 1

    def get_scene_list(self, **kwargs: object) -> object:
        assert kwargs.get("start_in_scene") is True
        return self.intervals


def _api(
    *,
    intervals: object | None = None,
    open_error: Exception | None = None,
    detect_error: Exception | None = None,
    frame_size: tuple[int, int] = (640, 240),
    manager_holder: list[_Manager] | None = None,
) -> SimpleNamespace:
    if intervals is None:
        intervals = [
            (_Timecode(0.0), _Timecode(2.0)),
            (_Timecode(2.0), _Timecode(4.0)),
        ]

    def open_video(_path: str) -> SimpleNamespace:
        if open_error is not None:
            raise open_error
        return SimpleNamespace(frame_size=frame_size)

    def scene_manager(*, stats_manager: object | None = None) -> _Manager:
        manager = _Manager(
            intervals=intervals, detect_error=detect_error, stats_manager=stats_manager
        )
        if manager_holder is not None:
            manager_holder.append(manager)
        return manager

    class AdaptiveDetector:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class ContentDetector:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class StatsManager:
        def save_to_csv(self, buffer: StringIO) -> None:
            buffer.write("frame,score\n0,1\n")

    return SimpleNamespace(
        SceneManager=scene_manager,
        open_video=open_video,
        AdaptiveDetector=AdaptiveDetector,
        ContentDetector=ContentDetector,
        StatsManager=StatsManager,
        VideoOpenFailure=_VideoOpenError,
    )


def test_unsupported_backend_and_detector_are_terminal(tmp_path: Path) -> None:
    detector = PySceneDetectShotDetector()
    with pytest.raises(AdapterError) as backend:
        detector.detect(tmp_path / "x.mp4", _config(backend="other"), duration_ms=4000)
    assert backend.value.code == "SHOT_UNSUPPORTED_BACKEND"
    with pytest.raises(AdapterError) as algorithm:
        detector.detect(tmp_path / "x.mp4", _config(detector="hash"), duration_ms=4000)
    assert algorithm.value.code == "SHOT_UNSUPPORTED_DETECTOR"


def test_library_intervals_become_internal_cuts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holders: list[_Manager] = []
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(
            intervals=[
                (_Timecode(0.0), _Timecode(2.0)),
                (_LegacyStamp(), _Timecode(4.0)),
            ],
            manager_holder=holders,
        ),
    )
    result = PySceneDetectShotDetector().detect(
        tmp_path / "clip.mp4", _config(debug=True), duration_ms=4000
    )
    assert [item.position_ms for item in result.boundaries] == [2000]
    assert result.boundaries[0].transition is TransitionKind.CUT
    assert "scene" not in result.boundaries[0].transition.name.lower()
    assert result.debug_stats == b"frame,score\n0,1\n"
    assert holders[0].progress is False
    assert holders[0].downscale == 2
    assert holders[0].detectors[0].kwargs["min_scene_len"] == 1
    assert holders[0].detectors[0].kwargs["adaptive_threshold"] == 3.0


def test_content_detector_is_selected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    holders: list[_Manager] = []
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(manager_holder=holders),
    )
    PySceneDetectShotDetector().detect(
        tmp_path / "clip.mp4", _config(detector="content"), duration_ms=4000
    )
    assert type(holders[0].detectors[0]).__name__ == "ContentDetector"
    assert holders[0].detectors[0].kwargs["threshold"] == 3.0


def test_missing_library_is_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> SimpleNamespace:
        raise ImportError("missing")

    monkeypatch.setattr("cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect", boom)
    with pytest.raises(AdapterError) as caught:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert caught.value.code == "SHOT_UNAVAILABLE"
    assert caught.value.retryable is True
    assert str(tmp_path) not in caught.value.message


def test_open_failures_are_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(open_error=_VideoOpenError("nope")),
    )
    with pytest.raises(AdapterError) as caught:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert caught.value.code == "SHOT_DECODE_FAILED"

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(open_error=OSError("io")),
    )
    with pytest.raises(AdapterError) as io_error:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert io_error.value.code == "SHOT_DECODE_FAILED"


def test_detect_runtime_failure_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(detect_error=RuntimeError("decode")),
    )
    with pytest.raises(AdapterError) as caught:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert caught.value.code == "SHOT_FAILED"
    assert caught.value.retryable is True


def test_malformed_library_output_is_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(intervals="bad"),
    )
    with pytest.raises(AdapterError) as not_list:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert not_list.value.code == "SHOT_FAILED"

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(intervals=[(_Timecode(0.0), _Timecode(1.0)), "pair"]),
    )
    with pytest.raises(AdapterError) as bad_pair:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert bad_pair.value.code == "SHOT_FAILED"

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(intervals=[(_Timecode(0.0), _Timecode(1.0)), (_Timecode(2.0),)]),
    )
    with pytest.raises(AdapterError) as short_pair:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert short_pair.value.code == "SHOT_FAILED"

    class Broken:
        def get_seconds(self) -> float:
            raise TypeError("nope")

    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(intervals=[(_Timecode(0.0), _Timecode(1.0)), (Broken(), _Timecode(4.0))]),
    )
    with pytest.raises(AdapterError) as seconds:
        PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert seconds.value.code == "SHOT_FAILED"


def test_out_of_range_and_duplicate_cuts_are_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intervals = [
        (_Timecode(0.0), _Timecode(2.0)),
        (_Timecode(0.0), _Timecode(2.0)),
        (_Timecode(2.0), _Timecode(3.0)),
        (_Timecode(2.0), _Timecode(4.0)),
        (_Timecode(4.0), _Timecode(4.0)),
    ]
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(intervals=intervals),
    )
    result = PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert [item.position_ms for item in result.boundaries] == [2000]


def test_debug_csv_without_save_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()

    class MuteStats:
        pass

    api.StatsManager = MuteStats
    monkeypatch.setattr("cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect", lambda: api)
    result = PySceneDetectShotDetector().detect(
        tmp_path / "clip.mp4", _config(debug=True), duration_ms=4000
    )
    assert result.debug_stats == b""


def test_no_internal_interval_yields_no_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.vision.pyscenedetect.load_scenedetect",
        lambda: _api(intervals=[(_Timecode(0.0), _Timecode(4.0))]),
    )
    result = PySceneDetectShotDetector().detect(tmp_path / "clip.mp4", _config(), duration_ms=4000)
    assert result.boundaries == ()
    assert result.debug_stats is None


def test_load_scenedetect_imports_the_pinned_api() -> None:
    from cine_analyzer.adapters.vision.pyscenedetect import load_scenedetect

    api = load_scenedetect()
    assert api.SceneManager is not None
    assert api.AdaptiveDetector is not None
    assert api.ContentDetector is not None
