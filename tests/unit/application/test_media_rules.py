"""Acceptance rules and the one duration rounding rule."""

import pytest
from tests.unit.application.fakes import REQUEST_ID, make_probe_facts, tiny_config

from cine_analyzer.application.errors import IngestError
from cine_analyzer.application.media_rules import (
    presentation_seconds_to_ms,
    seconds_to_ms,
    validate_probe_facts,
)


def test_seconds_to_ms_rounds_half_up() -> None:
    assert seconds_to_ms(1.0) == 1_000
    assert seconds_to_ms(1.5004) == 1_500
    assert seconds_to_ms(0.0005) == 1


def test_seconds_to_ms_rejects_non_positive_and_sub_millisecond_values() -> None:
    with pytest.raises(ValueError, match="positive"):
        seconds_to_ms(0.0)
    with pytest.raises(ValueError, match="positive"):
        seconds_to_ms(-1.0)
    with pytest.raises(ValueError, match="positive"):
        seconds_to_ms(0.0004)


def test_presentation_seconds_to_ms_allows_zero() -> None:
    assert presentation_seconds_to_ms(0.0) == 0
    assert presentation_seconds_to_ms(2.0) == 2000
    assert presentation_seconds_to_ms(0.0005) == 1
    with pytest.raises(ValueError, match="negative"):
        presentation_seconds_to_ms(-0.1)


def _reject(facts_overrides: dict[str, object], *, code: str, size_bytes: int = 64) -> None:
    with pytest.raises(IngestError) as caught:
        validate_probe_facts(
            make_probe_facts(**facts_overrides),
            tiny_config(),
            size_bytes=size_bytes,
            request_id=REQUEST_ID,
        )
    assert caught.value.safe.code == code
    assert caught.value.safe.request_id == REQUEST_ID


def test_validate_probe_facts_accepts_a_legal_clip() -> None:
    validate_probe_facts(make_probe_facts(), tiny_config(), size_bytes=64, request_id=REQUEST_ID)


def test_size_limit_is_enforced_before_other_rules() -> None:
    _reject({}, code="MEDIA_TOO_LARGE", size_bytes=2_048)


def test_stream_counts_are_enforced() -> None:
    _reject({"video_stream_count": 0}, code="MEDIA_VIDEO_STREAM_COUNT")
    _reject({"video_stream_count": 2}, code="MEDIA_VIDEO_STREAM_COUNT")
    _reject({"audio_stream_count": 2}, code="MEDIA_AUDIO_STREAM_COUNT")


def test_invalid_and_excessive_duration_are_rejected() -> None:
    _reject({"duration_ms": 0}, code="MEDIA_DURATION_INVALID")
    with pytest.raises(IngestError) as caught:
        validate_probe_facts(
            make_probe_facts(duration_ms=20_000),
            tiny_config(max_duration_ms=10_000),
            size_bytes=64,
            request_id=REQUEST_ID,
        )
    assert caught.value.safe.code == "MEDIA_DURATION_EXCEEDED"


def test_coded_and_display_dimensions_are_checked() -> None:
    _reject({"width": 0}, code="MEDIA_DIMENSIONS_INVALID")
    with pytest.raises(IngestError) as caught:
        validate_probe_facts(
            make_probe_facts(width=500, height=100, display_rotation_degrees=0),
            tiny_config(max_width=320, max_height=240),
            size_bytes=64,
            request_id=REQUEST_ID,
        )
    assert caught.value.safe.code == "MEDIA_DIMENSIONS_EXCEEDED"
    with pytest.raises(IngestError) as caught:
        validate_probe_facts(
            make_probe_facts(width=100, height=500, display_rotation_degrees=90),
            tiny_config(max_width=320, max_height=240),
            size_bytes=64,
            request_id=REQUEST_ID,
        )
    assert caught.value.safe.code == "MEDIA_DIMENSIONS_EXCEEDED"


def test_rotation_codec_hdr_and_audio_consistency() -> None:
    _reject({"display_rotation_degrees": 45}, code="MEDIA_UNSUPPORTED_ROTATION")
    _reject({"video_codec": "prores"}, code="MEDIA_UNSUPPORTED_CODEC")
    _reject({"color_transfer": "smpte2084"}, code="MEDIA_UNSUPPORTED_TRANSFER")
    _reject({"color_transfer": "smpte428_1"}, code="MEDIA_UNSUPPORTED_TRANSFER")
    _reject({"has_audio": True, "audio_codec": None}, code="MEDIA_AUDIO_INCONSISTENT")
    _reject({"has_audio": False, "audio_codec": "aac"}, code="MEDIA_AUDIO_INCONSISTENT")


def test_270_rotation_swaps_display_dimensions_for_limits() -> None:
    validate_probe_facts(
        make_probe_facts(width=240, height=320, display_rotation_degrees=270),
        tiny_config(max_width=320, max_height=240),
        size_bytes=64,
        request_id=REQUEST_ID,
    )
