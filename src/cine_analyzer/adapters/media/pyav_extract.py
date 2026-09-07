"""Ordered sample extraction with PyAV (ADR-0009)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import numpy as np
from numpy.typing import NDArray

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.media_rules import presentation_seconds_to_ms
from cine_analyzer.domain.media import SampleRequest
from cine_analyzer.domain.time import TimeRangeMs
from cine_analyzer.ports.shots import DecodedSample

__all__ = ["PyAvSampleExtractor", "load_av"]

_JPEG_QUALITY = 95
_OUTSIDE = "decoded timestamp is outside the requested shot"
_MISSING = "no frame at or after the requested timestamp"
_ROTATE_TURNS = {90: 1, 180: 2, 270: 3}


def _error(code: str, message: str, *, retryable: bool) -> AdapterError:
    return AdapterError(code, message, retryable=retryable, stage="sampling")


def load_av() -> SimpleNamespace:
    """Import PyAV. Isolated so tests can replace this function."""
    import av
    from av.error import FFmpegError

    return SimpleNamespace(open=av.open, FFmpegError=FFmpegError)


class PyAvSampleExtractor:
    """Decode in presentation order and capture the first frame at or after each request."""

    def extract(
        self,
        path: Path,
        requests: tuple[SampleRequest, ...],
        ranges: dict[UUID, TimeRangeMs],
        *,
        rotation_degrees: int,
    ) -> tuple[DecodedSample, ...]:
        """Return one result per request, in request order."""
        try:
            api = load_av()
        except ImportError as error:
            raise _error(
                "SHOT_EXTRACT_UNAVAILABLE",
                "sample extractor library is not available",
                retryable=True,
            ) from error
        try:
            container = api.open(str(path.resolve()))
        except OSError as error:
            raise _error(
                "SHOT_EXTRACT_FAILED",
                "the media file could not be decoded for sampling",
                retryable=False,
            ) from error
        except api.FFmpegError as error:
            raise _error(
                "SHOT_EXTRACT_FAILED",
                "the media file could not be decoded for sampling",
                retryable=False,
            ) from error
        try:
            return _extract_open(
                container,
                requests,
                ranges,
                rotation_degrees=rotation_degrees,
            )
        except api.FFmpegError as error:
            raise _error(
                "SHOT_EXTRACT_FAILED",
                "the media file could not be decoded for sampling",
                retryable=False,
            ) from error
        finally:
            closer = getattr(container, "close", None)
            if callable(closer):
                closer()


def _extract_open(
    container: object,
    requests: tuple[SampleRequest, ...],
    ranges: dict[UUID, TimeRangeMs],
    *,
    rotation_degrees: int,
) -> tuple[DecodedSample, ...]:
    streams = getattr(container, "streams", None)
    video_streams = getattr(streams, "video", None) if streams is not None else None
    if not video_streams:
        raise _error(
            "SHOT_EXTRACT_FAILED",
            "the media file could not be decoded for sampling",
            retryable=False,
        )
    pending = sorted(requests, key=lambda item: (item.requested_ms, item.sample_id.hex))
    captured: dict[UUID, DecodedSample] = {}
    frame_index = 0
    try:
        decoded = cast("Any", container).decode(video=0)
        for frame in decoded:
            _consume_frame(
                frame,
                pending,
                captured,
                ranges,
                frame_index=frame_index,
                rotation_degrees=rotation_degrees,
            )
            frame_index += 1
            if not pending:
                break
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        raise _error(
            "SHOT_EXTRACT_FAILED",
            "the media file could not be decoded for sampling",
            retryable=False,
        ) from error
    for leftover in pending:
        captured[leftover.sample_id] = DecodedSample(
            sample_id=leftover.sample_id,
            requested_ms=leftover.requested_ms,
            decoded_ms=None,
            frame_index=None,
            jpeg=None,
            unavailable_reason=_MISSING,
        )
    return tuple(captured[item.sample_id] for item in requests)


def _consume_frame(
    frame: object,
    pending: list[SampleRequest],
    captured: dict[UUID, DecodedSample],
    ranges: dict[UUID, TimeRangeMs],
    *,
    frame_index: int,
    rotation_degrees: int,
) -> None:
    decoded_ms = _frame_ms(frame)
    if decoded_ms is None:
        return
    while pending and pending[0].requested_ms <= decoded_ms:
        request = pending.pop(0)
        shot_range = ranges[request.shot_id]
        if decoded_ms < shot_range.start_ms or decoded_ms >= shot_range.end_ms:
            captured[request.sample_id] = DecodedSample(
                sample_id=request.sample_id,
                requested_ms=request.requested_ms,
                decoded_ms=None,
                frame_index=None,
                jpeg=None,
                unavailable_reason=_OUTSIDE,
            )
            continue
        captured[request.sample_id] = DecodedSample(
            sample_id=request.sample_id,
            requested_ms=request.requested_ms,
            decoded_ms=decoded_ms,
            frame_index=frame_index,
            jpeg=_encode_jpeg(frame, rotation_degrees=rotation_degrees),
            unavailable_reason=None,
        )


def _frame_ms(frame: object) -> int | None:
    time_value = getattr(frame, "time", None)
    if time_value is None:
        pts = getattr(frame, "pts", None)
        time_base = getattr(frame, "time_base", None)
        if pts is None or time_base is None:
            return None
        try:
            time_value = float(pts) * float(time_base)
        except (TypeError, ValueError):
            return None
    try:
        seconds = float(time_value)
    except (TypeError, ValueError):
        return None
    if seconds < 0.0:
        return None
    return presentation_seconds_to_ms(seconds)


def _encode_jpeg(frame: object, *, rotation_degrees: int) -> bytes:
    import cv2

    array = np.asarray(cast("Any", frame).to_ndarray(format="bgr24"), dtype=np.uint8)
    rotated = _rotate(array, rotation_degrees)
    ok, encoded = cv2.imencode(
        ".jpg",
        np.ascontiguousarray(rotated),
        [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY],
    )
    if not ok:
        raise _error(
            "SHOT_EXTRACT_FAILED",
            "a decoded frame could not be encoded as evidence",
            retryable=False,
        )
    return encoded.tobytes()


def _rotate(array: NDArray[np.uint8], rotation_degrees: int) -> NDArray[np.uint8]:
    turns = _ROTATE_TURNS.get(rotation_degrees)
    if turns is None:
        return array
    rotated: NDArray[np.uint8] = np.rot90(array, k=turns)
    return rotated
