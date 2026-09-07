"""FFmpeg extract: missing binary, timeout, size cap, non-zero exit, odd PCM."""

import subprocess
from pathlib import Path

import pytest

from cine_analyzer.adapters.media.ffmpeg_audio import FfmpegAudioExtractor
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.types import MetricStatus


class FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes | None = b"",
        returncode: int | None = 0,
        timeout: bool = False,
        pid: int = 4242,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.timeout = timeout
        self.pid = pid
        self.calls = 0
        self.killed = False

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes | None]:
        self.calls += 1
        if self.timeout and self.calls == 1:
            raise subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=timeout or 0)
        return self.stdout, self.stderr

    def kill(self) -> None:
        self.killed = True


def _extractor() -> FfmpegAudioExtractor:
    return FfmpegAudioExtractor("ffmpeg", timeout_ms=1000, max_stdout_bytes=32)


def _analyze(extractor: FfmpegAudioExtractor, path: Path) -> object:
    return extractor.analyze(
        path,
        has_audio=True,
        duration_ms=1000,
        config=AnalysisConfig().audio,
        window_starts_ms=(0,),
    )


def test_missing_binary_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which",
        lambda _name: None,
    )
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.status is MetricStatus.FAILED
    assert result.reason_code == "audio_extract_unavailable"


def test_timeout_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(timeout=True)
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", lambda *_a, **_k: process
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.os.killpg",
        lambda *_a, **_k: None,
    )
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.reason_code == "audio_extract_timeout"


def test_oversized_stdout_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(stdout=b"\x00" * 64)
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", lambda *_a, **_k: process
    )
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.reason_code == "audio_extract_too_large"


def test_nonzero_returncode_is_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(returncode=1)
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", lambda *_a, **_k: process
    )
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.reason_code == "audio_extract_failed"


def test_odd_length_pcm_is_trimmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(stdout=b"\x00\x10\x00")
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", lambda *_a, **_k: process
    )
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.status is MetricStatus.OK
    assert result.windows[0] is not None


def test_empty_pcm_is_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(stdout=b"")
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", lambda *_a, **_k: process
    )
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.status is MetricStatus.OK
    assert result.windows[0] is not None
    assert result.windows[0].rms_dbfs == -120.0


def test_popen_file_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr("cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", _raise)
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.reason_code == "audio_extract_unavailable"


def test_popen_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError

    monkeypatch.setattr("cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", _raise)
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.reason_code == "audio_extract_failed"


def test_kill_group_falls_back_when_the_process_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process = FakeProcess(timeout=True)

    def _missing(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", lambda *_a, **_k: process
    )
    monkeypatch.setattr("cine_analyzer.adapters.media.ffmpeg_audio.os.killpg", _missing)
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.reason_code == "audio_extract_timeout"
    assert process.killed is True


def test_none_returncode_and_stderr_are_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    process = FakeProcess(stdout=b"\x00\x00", stderr=None, returncode=None)
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.shutil.which", lambda _name: "/usr/bin/ffmpeg"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffmpeg_audio.subprocess.Popen", lambda *_a, **_k: process
    )
    result = _analyze(_extractor(), tmp_path / "clip.mp4")
    assert result.status is MetricStatus.OK
