"""PySceneDetect adapter. Third-party interval names are translated here only."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.media_rules import presentation_seconds_to_ms
from cine_analyzer.domain.config import ShotsConfig
from cine_analyzer.domain.shots import TransitionKind
from cine_analyzer.ports.shots import DetectedBoundary, DetectionResult

__all__ = ["PySceneDetectShotDetector", "load_scenedetect"]

_BACKEND = "pyscenedetect"
_ADAPTIVE = "adaptive"
_CONTENT = "content"


def _error(code: str, message: str, *, retryable: bool) -> AdapterError:
    return AdapterError(code, message, retryable=retryable, stage="shots")


def load_scenedetect() -> SimpleNamespace:
    """Import the detector library. Isolated so tests can replace this function."""
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import AdaptiveDetector, ContentDetector
    from scenedetect.stats_manager import StatsManager
    from scenedetect.video_stream import VideoOpenFailure

    return SimpleNamespace(
        SceneManager=SceneManager,
        open_video=open_video,
        AdaptiveDetector=AdaptiveDetector,
        ContentDetector=ContentDetector,
        StatsManager=StatsManager,
        VideoOpenFailure=VideoOpenFailure,
    )


class PySceneDetectShotDetector:
    """Detect internal edits with a pinned PySceneDetect backend."""

    def detect(self, path: Path, config: ShotsConfig, *, duration_ms: int) -> DetectionResult:
        """Return internal boundaries. ``path`` is never copied into the error."""
        if config.backend != _BACKEND:
            raise _error(
                "SHOT_UNSUPPORTED_BACKEND",
                "shot detector backend is not supported",
                retryable=False,
            )
        if config.detector not in {_ADAPTIVE, _CONTENT}:
            raise _error(
                "SHOT_UNSUPPORTED_DETECTOR",
                "shot detector algorithm is not supported",
                retryable=False,
            )
        try:
            api = load_scenedetect()
        except ImportError as error:
            raise _error(
                "SHOT_UNAVAILABLE",
                "shot detector library is not available",
                retryable=True,
            ) from error
        stats = api.StatsManager() if config.debug else None
        try:
            video = api.open_video(str(path.resolve()))
        except api.VideoOpenFailure as error:
            raise _error(
                "SHOT_DECODE_FAILED",
                "the media file could not be decoded for shot detection",
                retryable=False,
            ) from error
        except OSError as error:
            raise _error(
                "SHOT_DECODE_FAILED",
                "the media file could not be decoded for shot detection",
                retryable=False,
            ) from error
        try:
            manager = api.SceneManager(stats_manager=stats)
            manager.auto_downscale = False
            width = int(video.frame_size[0])
            manager.downscale = max(1, int(width / config.working_width + 0.5))
            if config.detector == _ADAPTIVE:
                manager.add_detector(
                    api.AdaptiveDetector(
                        adaptive_threshold=config.threshold,
                        min_scene_len=1,
                        min_content_val=config.min_content_val,
                    )
                )
            else:
                manager.add_detector(
                    api.ContentDetector(threshold=config.threshold, min_scene_len=1)
                )
            manager.detect_scenes(video, show_progress=False)
            interval_list = manager.get_scene_list(start_in_scene=True)
        except (OSError, RuntimeError, ValueError, AttributeError, TypeError) as error:
            raise _error(
                "SHOT_FAILED",
                "shot detection failed",
                retryable=True,
            ) from error
        boundaries = _internal_boundaries(interval_list, duration_ms=duration_ms)
        debug_stats = _debug_csv(stats) if stats is not None else None
        return DetectionResult(boundaries=boundaries, debug_stats=debug_stats)


def _internal_boundaries(
    interval_list: object, *, duration_ms: int
) -> tuple[DetectedBoundary, ...]:
    if not isinstance(interval_list, list):
        raise _error(
            "SHOT_FAILED",
            "shot detection failed",
            retryable=False,
        )
    collected: list[DetectedBoundary] = []
    seen: set[int] = set()
    for index, pair in enumerate(interval_list):
        if index == 0:
            continue
        if not isinstance(pair, tuple):
            raise _error(
                "SHOT_FAILED",
                "shot detection failed",
                retryable=False,
            )
        try:
            start, _end = pair
        except (TypeError, ValueError) as error:
            raise _error(
                "SHOT_FAILED",
                "shot detection failed",
                retryable=False,
            ) from error
        try:
            raw = getattr(start, "seconds", None)
            if raw is None:
                raw = start.get_seconds()
            seconds = float(raw)
            position_ms = presentation_seconds_to_ms(seconds)
        except (AttributeError, TypeError, ValueError) as error:
            raise _error(
                "SHOT_FAILED",
                "shot detection failed",
                retryable=False,
            ) from error
        if position_ms <= 0 or position_ms >= duration_ms or position_ms in seen:
            continue
        seen.add(position_ms)
        collected.append(
            DetectedBoundary(
                position_ms=position_ms,
                transition=TransitionKind.CUT,
                detector_score=None,
            )
        )
    return tuple(collected)


def _debug_csv(stats: object) -> bytes:
    buffer = StringIO()
    save = getattr(stats, "save_to_csv", None)
    if save is None:
        return b""
    save(buffer)
    return buffer.getvalue().encode("utf-8")
