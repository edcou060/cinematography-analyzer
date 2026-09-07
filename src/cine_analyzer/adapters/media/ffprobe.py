"""ffprobe adapter. Argument arrays only; never a shell."""

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any, cast

from cine_analyzer.adapters.media.childproc import popen_limit_kwargs
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.media_rules import seconds_to_ms
from cine_analyzer.domain.media import ROTATION_DEGREES
from cine_analyzer.domain.time import Rational
from cine_analyzer.ports.ingestion import ProbeFacts

__all__ = ["STDERR_LIMIT_BYTES", "STDOUT_LIMIT_BYTES", "FfprobeMediaProbe", "parse_ffprobe_json"]

STDERR_LIMIT_BYTES = 8_192
STDOUT_LIMIT_BYTES = 1_048_576
_VIDEO = "video"
_AUDIO = "audio"
_ALLOWED_TYPES = {_VIDEO, _AUDIO}


def _error(code: str, message: str, *, retryable: bool) -> AdapterError:
    stage = "probe" if code.startswith("PROBE_") else "ingest"
    return AdapterError(code, message, retryable=retryable, stage=stage)


class FfprobeMediaProbe:
    """Characterise a local media file with ffprobe JSON output."""

    def __init__(self, binary: str, *, timeout_ms: int) -> None:
        self._binary = binary
        self._timeout_ms = timeout_ms

    def probe(self, path: Path) -> ProbeFacts:
        """Return normalised facts or raise AdapterError. ``path`` is never in the error."""
        resolved_binary = shutil.which(self._binary)
        if resolved_binary is None:
            raise _error(
                "PROBE_UNAVAILABLE",
                "ffprobe is not available on PATH",
                retryable=True,
            )
        argv = [
            resolved_binary,
            "-hide_banner",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-i",
            f"file:{path.resolve()}",
        ]
        stdout, returncode = _run_ffprobe(argv, timeout_s=self._timeout_ms / 1000.0)
        if returncode != 0:
            raise _error(
                "MEDIA_CORRUPT",
                "the media file could not be probed",
                retryable=False,
            )
        return parse_ffprobe_json(stdout)


def _run_ffprobe(argv: list[str], *, timeout_s: float) -> tuple[bytes, int]:
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
            **popen_limit_kwargs(),
        )
    except FileNotFoundError as error:
        raise _error(
            "PROBE_UNAVAILABLE",
            "ffprobe is not available on PATH",
            retryable=True,
        ) from error
    except OSError as error:
        raise _error(
            "PROBE_FAILED",
            "ffprobe could not be started",
            retryable=True,
        ) from error
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as error:
        _kill_group(process)
        process.communicate(timeout=5)
        raise _error(
            "PROBE_TIMEOUT",
            "ffprobe exceeded the configured wall-time limit",
            retryable=True,
        ) from error
    _bound_stderr(stderr)
    if len(stdout) > STDOUT_LIMIT_BYTES:
        raise _error(
            "PROBE_FAILED",
            "probe output exceeded the bounded size limit",
            retryable=False,
        )
    return stdout, int(process.returncode or 0)


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process.kill()


def _bound_stderr(stderr: bytes | None) -> None:
    if stderr is None:
        return
    # Intentionally discarded after bounding. Never copied into SafeError.
    _ = stderr[:STDERR_LIMIT_BYTES]


def parse_ffprobe_json(payload: bytes) -> ProbeFacts:
    """Parse ffprobe JSON into ProbeFacts. Used by tests with fixture bytes."""
    try:
        decoded: object = json.loads(payload)
    except json.JSONDecodeError as error:
        raise _error(
            "PROBE_FAILED",
            "probe output was not valid JSON",
            retryable=False,
        ) from error
    if not isinstance(decoded, dict):
        raise _error(
            "PROBE_FAILED",
            "probe output was not a JSON object",
            retryable=False,
        )
    document = cast("dict[str, Any]", decoded)
    streams = document.get("streams")
    format_section = document.get("format")
    if not isinstance(streams, list) or not isinstance(format_section, dict):
        raise _error(
            "PROBE_FAILED",
            "probe output did not include format and streams",
            retryable=False,
        )
    video_streams: list[dict[str, Any]] = []
    audio_streams: list[dict[str, Any]] = []
    for stream in streams:
        if not isinstance(stream, dict):
            raise _error(
                "PROBE_FAILED",
                "probe output contained a malformed stream",
                retryable=False,
            )
        codec_type = stream.get("codec_type")
        if codec_type not in _ALLOWED_TYPES:
            raise _error(
                "MEDIA_UNEXPECTED_STREAM",
                "only video and audio streams are accepted",
                retryable=False,
            )
        if codec_type == _VIDEO:
            video_streams.append(stream)
        else:
            audio_streams.append(stream)
    duration_ms = _duration_ms(format_section)
    video_codec = ""
    pixel_format: str | None = None
    width = 0
    height = 0
    rotation = 0
    average = Rational(numerator=1, denominator=1)
    real_rate: Rational | None = None
    color_transfer: str | None = None
    if len(video_streams) == 1:
        video = video_streams[0]
        video_codec = _codec_name(video)
        pixel_format = _optional_str(video.get("pix_fmt"))
        width, height = _dimensions(video)
        rotation = _rotation(video)
        average = _required_frame_rate(video.get("avg_frame_rate"))
        real_rate = _optional_frame_rate(video.get("r_frame_rate"))
        color_transfer = _optional_str(video.get("color_transfer"))
    has_audio = False
    audio_codec: str | None = None
    if len(audio_streams) == 1:
        audio_name = audio_streams[0].get("codec_name")
        if not isinstance(audio_name, str) or audio_name.strip() == "":
            raise _error(
                "MEDIA_AUDIO_INCONSISTENT",
                "audio presence and codec metadata are inconsistent",
                retryable=False,
            )
        has_audio = True
        audio_codec = audio_name.strip()
    return ProbeFacts(
        duration_ms=duration_ms,
        width=width,
        height=height,
        display_rotation_degrees=rotation,
        average_frame_rate=average,
        real_frame_rate=real_rate,
        video_codec=video_codec,
        pixel_format=pixel_format,
        has_audio=has_audio,
        audio_codec=audio_codec,
        color_transfer=color_transfer,
        video_stream_count=len(video_streams),
        audio_stream_count=len(audio_streams),
        raw_json=payload,
    )


def _duration_ms(format_section: dict[str, Any]) -> int:
    raw = format_section.get("duration")
    if raw is None:
        raise _error(
            "MEDIA_DURATION_INVALID",
            "probed duration must be positive",
            retryable=False,
        )
    try:
        seconds = float(raw)
    except (TypeError, ValueError) as error:
        raise _error(
            "MEDIA_DURATION_INVALID",
            "probed duration must be positive",
            retryable=False,
        ) from error
    try:
        return seconds_to_ms(seconds)
    except ValueError as error:
        raise _error(
            "MEDIA_DURATION_INVALID",
            "probed duration must be positive",
            retryable=False,
        ) from error


def _codec_name(stream: dict[str, Any]) -> str:
    name = stream.get("codec_name")
    if not isinstance(name, str) or name.strip() == "":
        message = "stream codec is missing"
        raise _error("MEDIA_UNSUPPORTED_CODEC", message, retryable=False)
    return name.strip()


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if stripped == "" or stripped.lower() in {"unknown", "unspecified"}:
        return None
    return stripped


def _dimensions(stream: dict[str, Any]) -> tuple[int, int]:
    try:
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise _error(
            "MEDIA_DIMENSIONS_INVALID",
            "video stream dimensions are missing",
            retryable=False,
        ) from error
    if width <= 0 or height <= 0:
        raise _error(
            "MEDIA_DIMENSIONS_INVALID",
            "video stream dimensions are missing",
            retryable=False,
        )
    return width, height


def _required_frame_rate(raw: object) -> Rational:
    parsed = _optional_frame_rate(raw)
    if parsed is None:
        raise _error(
            "MEDIA_FRAME_RATE_UNKNOWN",
            "average frame rate could not be parsed",
            retryable=False,
        )
    return parsed


def _optional_frame_rate(raw: object) -> Rational | None:
    if not isinstance(raw, str) or raw in {"0/0", "N/A"}:
        return None
    numerator_text, separator, denominator_text = raw.partition("/")
    if separator == "":
        try:
            numerator = int(raw)
        except ValueError:
            return None
        if numerator <= 0:
            return None
        return Rational(numerator=numerator, denominator=1)
    try:
        numerator = int(numerator_text)
        denominator = int(denominator_text)
    except ValueError:
        return None
    if denominator <= 0 or numerator <= 0:
        return None
    return Rational(numerator=numerator, denominator=denominator)


def _rotation(stream: dict[str, Any]) -> int:
    tags = stream.get("tags")
    if isinstance(tags, dict):
        tagged = tags.get("rotate", tags.get("ROTATE"))
        if tagged is not None:
            return _normalise_rotation(tagged)
    side_data = stream.get("side_data_list")
    if isinstance(side_data, list):
        for item in side_data:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("side_data_type", ""))
            if "display matrix" in kind.lower() and "rotation" in item:
                return _normalise_rotation(item["rotation"])
    return 0


def _normalise_rotation(raw: object) -> int:
    if not isinstance(raw, int | float | str):
        raise _error(
            "MEDIA_UNSUPPORTED_ROTATION",
            "display rotation must be a right angle",
            retryable=False,
        )
    try:
        degrees = round(float(raw)) % 360
    except (TypeError, ValueError) as error:
        raise _error(
            "MEDIA_UNSUPPORTED_ROTATION",
            "display rotation must be a right angle",
            retryable=False,
        ) from error
    if degrees not in ROTATION_DEGREES:
        raise _error(
            "MEDIA_UNSUPPORTED_ROTATION",
            "display rotation must be a right angle",
            retryable=False,
        )
    return degrees
