"""Acceptance rules applied to probe facts. One rounding rule for time: round half up to ms."""

from cine_analyzer.application.errors import ingest_error
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.media import ROTATION_DEGREES
from cine_analyzer.ports.ingestion import ProbeFacts

__all__ = [
    "ACCEPTED_VIDEO_CODECS",
    "HDR_TRANSFERS",
    "presentation_seconds_to_ms",
    "seconds_to_ms",
    "validate_probe_facts",
]

ACCEPTED_VIDEO_CODECS = frozenset({"h264", "hevc", "vp9", "av1", "mpeg4"})
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67", "smpte428", "smpte428-1"})


def seconds_to_ms(seconds: float) -> int:
    """Convert a presentation duration to integer milliseconds, rounding half up.

    Applied once at the ingest boundary. The value is never converted back to
    seconds for further computation.
    """
    if seconds <= 0.0:
        message = "probed duration must be positive"
        raise ValueError(message)
    converted = int(seconds * 1000.0 + 0.5)
    if converted <= 0:
        message = "probed duration must be positive"
        raise ValueError(message)
    return converted


def presentation_seconds_to_ms(seconds: float) -> int:
    """Convert a presentation timestamp to integer milliseconds, rounding half up.

    Zero is a valid timestamp (media start). Negative values are rejected.
    """
    if seconds < 0.0:
        message = "presentation timestamp cannot be negative"
        raise ValueError(message)
    return int(seconds * 1000.0 + 0.5)


def _display_dimensions(facts: ProbeFacts) -> tuple[int, int]:
    if facts.display_rotation_degrees in {90, 270}:
        return facts.height, facts.width
    return facts.width, facts.height


def validate_probe_facts(
    facts: ProbeFacts,
    config: AnalysisConfig,
    *,
    size_bytes: int,
    request_id: str,
) -> None:
    """Reject unsupported or over-limit media. Messages contain no paths."""
    limits = config.limits
    if size_bytes > limits.max_upload_bytes:
        raise ingest_error(
            "MEDIA_TOO_LARGE",
            "upload exceeds the configured size limit",
            request_id=request_id,
            retryable=False,
        )
    if facts.video_stream_count != 1:
        raise ingest_error(
            "MEDIA_VIDEO_STREAM_COUNT",
            "exactly one video stream is required",
            request_id=request_id,
            retryable=False,
        )
    if facts.audio_stream_count > 1:
        raise ingest_error(
            "MEDIA_AUDIO_STREAM_COUNT",
            "at most one audio stream is accepted",
            request_id=request_id,
            retryable=False,
        )
    if facts.width <= 0 or facts.height <= 0:
        raise ingest_error(
            "MEDIA_DIMENSIONS_INVALID",
            "video stream dimensions are missing",
            request_id=request_id,
            retryable=False,
        )
    if facts.duration_ms <= 0:
        raise ingest_error(
            "MEDIA_DURATION_INVALID",
            "probed duration must be positive",
            request_id=request_id,
            retryable=False,
        )
    if facts.duration_ms > limits.max_duration_ms:
        raise ingest_error(
            "MEDIA_DURATION_EXCEEDED",
            "probed duration exceeds the configured limit",
            request_id=request_id,
            retryable=False,
        )
    display_width, display_height = _display_dimensions(facts)
    if display_width > limits.max_width or display_height > limits.max_height:
        raise ingest_error(
            "MEDIA_DIMENSIONS_EXCEEDED",
            "display dimensions exceed the configured limit",
            request_id=request_id,
            retryable=False,
        )
    if facts.display_rotation_degrees not in ROTATION_DEGREES:
        raise ingest_error(
            "MEDIA_UNSUPPORTED_ROTATION",
            "display rotation must be a right angle",
            request_id=request_id,
            retryable=False,
        )
    if facts.video_codec not in ACCEPTED_VIDEO_CODECS:
        raise ingest_error(
            "MEDIA_UNSUPPORTED_CODEC",
            "video codec is not in the accepted set",
            request_id=request_id,
            retryable=False,
        )
    transfer = facts.color_transfer
    if transfer is not None and transfer.lower().replace("_", "-") in HDR_TRANSFERS:
        raise ingest_error(
            "MEDIA_UNSUPPORTED_TRANSFER",
            "HDR transfer characteristics are not accepted",
            request_id=request_id,
            retryable=False,
        )
    if facts.has_audio != (facts.audio_codec is not None):
        raise ingest_error(
            "MEDIA_AUDIO_INCONSISTENT",
            "audio presence and codec metadata are inconsistent",
            request_id=request_id,
            retryable=False,
        )
