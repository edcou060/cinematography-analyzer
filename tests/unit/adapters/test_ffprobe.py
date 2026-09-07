"""ffprobe adapter: argv lists, bounded IO, JSON normalised into ProbeFacts."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cine_analyzer.adapters.media.ffprobe import (
    STDERR_LIMIT_BYTES,
    STDOUT_LIMIT_BYTES,
    FfprobeMediaProbe,
    parse_ffprobe_json,
)
from cine_analyzer.application.errors import AdapterError


def _video_stream(**overrides: object) -> dict[str, object]:
    stream: dict[str, object] = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 320,
        "height": 240,
        "avg_frame_rate": "25/1",
        "r_frame_rate": "25/1",
        "pix_fmt": "yuv420p",
        "color_transfer": "bt709",
    }
    stream.update(overrides)
    return stream


def _payload(
    streams: list[dict[str, object]] | None = None, *, duration: object = "1.000"
) -> bytes:
    return json.dumps(
        {
            "format": {"duration": duration},
            "streams": streams if streams is not None else [_video_stream()],
        }
    ).encode()


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes | None = b"{}",
        stderr: bytes | None = b"",
        returncode: int | None = 0,
        pid: int | None = 4242,
        timeout: bool = False,
        second_timeout: bool = False,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.pid = pid
        self.timeout = timeout
        self.second_timeout = second_timeout
        self.calls = 0
        self.killed = False

    def communicate(self, timeout: float | None = None) -> tuple[bytes | None, bytes | None]:
        self.calls += 1
        if self.timeout and self.calls == 1:
            raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=timeout or 0)
        if self.second_timeout and self.calls == 2:
            raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=timeout or 0)
        return self.stdout, self.stderr

    def kill(self) -> None:
        self.killed = True


def test_parse_accepts_a_simple_video_stream() -> None:
    facts = parse_ffprobe_json(_payload())
    assert facts.duration_ms == 1_000
    assert facts.width == 320
    assert facts.height == 240
    assert facts.video_codec == "h264"
    assert facts.has_audio is False
    assert facts.video_stream_count == 1
    assert facts.average_frame_rate.numerator == 25


def test_parse_accepts_audio_and_display_matrix_rotation() -> None:
    video = _video_stream(
        tags={},
        side_data_list=[
            "ignore",
            {"side_data_type": "Display Matrix", "rotation": -90},
        ],
        avg_frame_rate="30",
        r_frame_rate="0/0",
        pix_fmt="unknown",
        color_transfer="unspecified",
    )
    audio = {"codec_type": "audio", "codec_name": "aac"}
    facts = parse_ffprobe_json(_payload([video, audio], duration="2.4"))
    assert facts.display_rotation_degrees == 270
    assert facts.has_audio is True
    assert facts.audio_codec == "aac"
    assert facts.real_frame_rate is None
    assert facts.pixel_format is None
    assert facts.color_transfer is None
    assert facts.duration_ms == 2_400


def test_rotate_tag_wins_over_display_matrix() -> None:
    video = _video_stream(
        tags={"rotate": "90"},
        side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90}],
    )
    assert parse_ffprobe_json(_payload([video])).display_rotation_degrees == 90


def test_parse_rejects_malformed_and_unsupported_documents() -> None:
    cases: list[tuple[bytes, str]] = [
        (b"not-json", "PROBE_FAILED"),
        (b"[]", "PROBE_FAILED"),
        (json.dumps({"format": {}, "streams": "nope"}).encode(), "PROBE_FAILED"),
        (json.dumps({"streams": []}).encode(), "PROBE_FAILED"),
        (json.dumps({"format": {}, "streams": ["bad"]}).encode(), "PROBE_FAILED"),
        (
            _payload([_video_stream(), {"codec_type": "subtitle", "codec_name": "mov_text"}]),
            "MEDIA_UNEXPECTED_STREAM",
        ),
        (_payload(duration=None), "MEDIA_DURATION_INVALID"),
        (_payload(duration="nope"), "MEDIA_DURATION_INVALID"),
        (_payload(duration="0"), "MEDIA_DURATION_INVALID"),
        (_payload([_video_stream(width="x")]), "MEDIA_DIMENSIONS_INVALID"),
        (_payload([_video_stream(width=0, height=240)]), "MEDIA_DIMENSIONS_INVALID"),
        (_payload([_video_stream(avg_frame_rate="0/0")]), "MEDIA_FRAME_RATE_UNKNOWN"),
        (_payload([_video_stream(avg_frame_rate="bad")]), "MEDIA_FRAME_RATE_UNKNOWN"),
        (_payload([_video_stream(avg_frame_rate="5/0")]), "MEDIA_FRAME_RATE_UNKNOWN"),
        (_payload([_video_stream(avg_frame_rate="0")]), "MEDIA_FRAME_RATE_UNKNOWN"),
        (_payload([_video_stream(avg_frame_rate="5/x")]), "MEDIA_FRAME_RATE_UNKNOWN"),
        (_payload([_video_stream(codec_name="")]), "MEDIA_UNSUPPORTED_CODEC"),
        (_payload([_video_stream(tags={"rotate": "45"})]), "MEDIA_UNSUPPORTED_ROTATION"),
        (_payload([_video_stream(tags={"rotate": "turn"})]), "MEDIA_UNSUPPORTED_ROTATION"),
        (_payload([_video_stream(tags={"rotate": []})]), "MEDIA_UNSUPPORTED_ROTATION"),
        (
            _payload([_video_stream(), {"codec_type": "audio", "codec_name": ""}]),
            "MEDIA_AUDIO_INCONSISTENT",
        ),
    ]
    for payload, code in cases:
        with pytest.raises(AdapterError) as caught:
            parse_ffprobe_json(payload)
        assert caught.value.code == code, payload


def test_non_string_optional_fields_are_absent() -> None:
    facts = parse_ffprobe_json(_payload([_video_stream(pix_fmt=1, color_transfer=1)]))
    assert facts.pixel_format is None
    assert facts.color_transfer is None
    facts = parse_ffprobe_json(_payload([_video_stream(pix_fmt="")]))
    assert facts.pixel_format is None


def test_display_matrix_without_rotation_defaults_to_zero() -> None:
    video = _video_stream(side_data_list=[{"side_data_type": "Display Matrix"}])
    assert parse_ffprobe_json(_payload([video])).display_rotation_degrees == 0
    facts = parse_ffprobe_json(_payload([_video_stream(r_frame_rate="24")]))
    assert facts.real_frame_rate is not None
    assert facts.real_frame_rate.numerator == 24


def test_probe_uses_an_argument_array_and_the_file_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    source = tmp_path / "-evil; rm -rf.mp4"
    source.write_bytes(b"x")
    fake = FakeProcess(stdout=_payload(), stderr=b"x" * (STDERR_LIMIT_BYTES + 50))

    def fake_popen(argv: list[str], **kwargs: object) -> FakeProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return fake

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: "/usr/bin/ffprobe"
    )
    monkeypatch.setattr("cine_analyzer.adapters.media.ffprobe.subprocess.Popen", fake_popen)

    facts = FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(source)

    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert "preexec_fn" in captured["kwargs"]
    assert captured["argv"][0] == "/usr/bin/ffprobe"
    assert "-nostdin" not in captured["argv"]
    assert "-i" in captured["argv"]
    assert captured["argv"][captured["argv"].index("-i") + 1].startswith("file:")
    assert "rm -rf" in captured["argv"][captured["argv"].index("-i") + 1]
    assert facts.video_codec == "h264"


def test_missing_binary_is_probe_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: None)
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(tmp_path / "x.mp4")
    assert caught.value.code == "PROBE_UNAVAILABLE"


def test_popen_file_not_found_and_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: "/usr/bin/ffprobe"
    )
    path = tmp_path / "x.mp4"
    path.write_bytes(b"x")

    def missing(_argv: list[str], **_kwargs: object) -> FakeProcess:
        raise FileNotFoundError("gone")

    monkeypatch.setattr("cine_analyzer.adapters.media.ffprobe.subprocess.Popen", missing)
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(path)
    assert caught.value.code == "PROBE_UNAVAILABLE"

    def denied(_argv: list[str], **_kwargs: object) -> FakeProcess:
        raise PermissionError("nope")

    monkeypatch.setattr("cine_analyzer.adapters.media.ffprobe.subprocess.Popen", denied)
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(path)
    assert caught.value.code == "PROBE_FAILED"


def test_nonzero_return_is_corrupt_media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: "/usr/bin/ffprobe"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.subprocess.Popen",
        lambda *_a, **_k: FakeProcess(stdout=b"", stderr=b"err", returncode=1),
    )
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(tmp_path)
    assert caught.value.code == "MEDIA_CORRUPT"


def test_timeout_kills_the_process_group(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    killed: list[int] = []
    fake = FakeProcess(timeout=True, pid=99)

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: "/usr/bin/ffprobe"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.subprocess.Popen", lambda *_a, **_k: fake
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.os.killpg", lambda pid, _sig: killed.append(pid)
    )

    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(tmp_path)
    assert caught.value.code == "PROBE_TIMEOUT"
    assert killed == [99]


def test_timeout_falls_back_to_kill_when_the_group_is_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeProcess(timeout=True, pid=7)

    def missing(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: "/usr/bin/ffprobe"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.subprocess.Popen", lambda *_a, **_k: fake
    )
    monkeypatch.setattr("cine_analyzer.adapters.media.ffprobe.os.killpg", missing)

    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(tmp_path)
    assert caught.value.code == "PROBE_TIMEOUT"
    assert fake.killed is True


def test_stdout_empty_returncode_none_and_oversize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: "/usr/bin/ffprobe"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.subprocess.Popen",
        lambda *_a, **_k: FakeProcess(stdout=b"", stderr=None, returncode=None),
    )
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(tmp_path)
    assert caught.value.code == "PROBE_FAILED"

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.subprocess.Popen",
        lambda *_a, **_k: FakeProcess(stdout=b"x" * (STDOUT_LIMIT_BYTES + 1), returncode=0),
    )
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1_000).probe(tmp_path)
    assert caught.value.code == "PROBE_FAILED"


def test_two_video_streams_are_counted_without_taking_the_first_as_canonical() -> None:
    facts = parse_ffprobe_json(_payload([_video_stream(), _video_stream(width=640)]))
    assert facts.video_stream_count == 2
    assert facts.width == 0


def test_rotate_tag_alternate_case() -> None:
    facts = parse_ffprobe_json(_payload([_video_stream(tags={"ROTATE": "180"})]))
    assert facts.display_rotation_degrees == 180
