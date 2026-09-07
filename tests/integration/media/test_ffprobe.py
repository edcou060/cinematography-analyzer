"""Real ffprobe against generated fixtures."""

from pathlib import Path

import pytest

from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.application.errors import AdapterError


def test_two_color_cut_is_a_short_h264_clip(video_fixtures: Path) -> None:
    probe = FfprobeMediaProbe("ffprobe", timeout_ms=15_000)
    facts = probe.probe(video_fixtures / "two_color_cut.mp4")

    assert facts.video_stream_count == 1
    assert facts.audio_stream_count == 0
    assert facts.video_codec == "h264"
    assert facts.width == 320
    assert facts.height == 240
    assert facts.has_audio is False
    assert 3_500 <= facts.duration_ms <= 4_500


def test_rotated_fixture_exposes_a_right_angle(video_fixtures: Path) -> None:
    facts = FfprobeMediaProbe("ffprobe", timeout_ms=15_000).probe(video_fixtures / "rotated_90.mp4")
    assert facts.display_rotation_degrees in {90, 270}


def test_no_audio_fixture_has_no_audio_stream(video_fixtures: Path) -> None:
    facts = FfprobeMediaProbe("ffprobe", timeout_ms=15_000).probe(video_fixtures / "no_audio.mp4")
    assert facts.has_audio is False
    assert facts.audio_stream_count == 0


def test_corrupt_fixture_is_rejected(video_fixtures: Path) -> None:
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=15_000).probe(video_fixtures / "corrupt.mp4")
    assert caught.value.code == "MEDIA_CORRUPT"
    assert str(video_fixtures) not in caught.value.message
