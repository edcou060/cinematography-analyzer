"""FFmpeg mono PCM extract and window features (ADR-0016). No LUFS library."""

import math
import os
import shutil
import signal
import subprocess
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from cine_analyzer.adapters.media.childproc import popen_limit_kwargs
from cine_analyzer.domain.config import AudioConfig
from cine_analyzer.domain.temporal import AudioWindowValue
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.audio import AudioAnalyzeResult

__all__ = [
    "FfmpegAudioExtractor",
    "window_features",
]

_STDERR_LIMIT = 8_192
_FFT_SIZE = 512
_FFT_HOP = 256
_LOG_EPS = 1e-12
_NO_AUDIO = "no_audio_stream"
_EXTRACT_FAILED = "audio_extract_failed"
_EXTRACT_TIMEOUT = "audio_extract_timeout"
_EXTRACT_UNAVAILABLE = "audio_extract_unavailable"
_EXTRACT_TOO_LARGE = "audio_extract_too_large"


class FfmpegAudioExtractor:
    """Mono s16le extract with timeout and stdout bound. Degrades instead of failing the report."""

    def __init__(self, binary: str, *, timeout_ms: int, max_stdout_bytes: int) -> None:
        self._binary = binary
        self._timeout_ms = timeout_ms
        self._max_stdout_bytes = max_stdout_bytes

    def analyze(
        self,
        source: Path,
        *,
        has_audio: bool,
        duration_ms: int,
        config: AudioConfig,
        window_starts_ms: tuple[int, ...],
    ) -> AudioAnalyzeResult:
        """Return window features, NO_AUDIO, or a named extract failure."""
        empty = tuple(None for _ in window_starts_ms)
        if not has_audio:
            return AudioAnalyzeResult(
                status=MetricStatus.NO_AUDIO,
                reason_code=_NO_AUDIO,
                windows=empty,
            )
        pcm, reason = self._extract(source, sample_rate_hz=config.sample_rate_hz)
        if pcm is None:
            return AudioAnalyzeResult(
                status=MetricStatus.FAILED,
                reason_code=reason or _EXTRACT_FAILED,
                windows=empty,
            )
        windows = tuple(
            window_features(
                pcm,
                sample_rate_hz=config.sample_rate_hz,
                start_ms=start,
                window_ms=config.window_ms,
                duration_ms=duration_ms,
            )
            for start in window_starts_ms
        )
        return AudioAnalyzeResult(status=MetricStatus.OK, reason_code=None, windows=windows)

    def _extract(
        self,
        source: Path,
        *,
        sample_rate_hz: int,
    ) -> tuple[NDArray[np.float64] | None, str | None]:
        resolved = shutil.which(self._binary)
        if resolved is None:
            return None, _EXTRACT_UNAVAILABLE
        argv = [
            resolved,
            "-hide_banner",
            "-nostdin",
            "-i",
            f"file:{source.resolve()}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate_hz),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "pipe:1",
        ]
        try:
            payload, returncode = _run_ffmpeg(
                argv,
                timeout_s=self._timeout_ms / 1000.0,
                max_stdout_bytes=self._max_stdout_bytes,
            )
        except _ExtractError as error:
            return None, error.reason
        if returncode != 0:
            return None, _EXTRACT_FAILED
        usable = len(payload) - (len(payload) % 2)
        if usable <= 0:
            return np.zeros(0, dtype=np.float64), None
        samples = np.frombuffer(payload[:usable], dtype=np.int16).astype(np.float64) / 32768.0
        return samples, None


class _ExtractError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def window_features(
    pcm: NDArray[np.float64],
    *,
    sample_rate_hz: int,
    start_ms: int,
    window_ms: int,
    duration_ms: int,
) -> AudioWindowValue:
    """RMS/dBFS, spectral flux, and onset (rectified flux) for one window. LUFS is omitted."""
    start = max(0, int(start_ms * sample_rate_hz / 1000))
    end_ms = min(start_ms + window_ms, duration_ms)
    end = max(start, int(end_ms * sample_rate_hz / 1000))
    samples = pcm[start:end]
    if samples.size == 0:
        return AudioWindowValue(
            rms_dbfs=-120.0,
            onset_strength=0.0,
            spectral_flux=0.0,
            loudness_lufs_short_term=None,
        )
    rms = float(np.sqrt(np.mean(np.square(samples))))
    dbfs = 20.0 * math.log10(rms + _LOG_EPS)
    flux = _spectral_flux(samples)
    return AudioWindowValue(
        rms_dbfs=dbfs,
        onset_strength=flux,
        spectral_flux=flux,
        loudness_lufs_short_term=None,
    )


def _spectral_flux(samples: NDArray[np.float64]) -> float:
    if samples.size < _FFT_SIZE:
        return 0.0
    window = np.hanning(_FFT_SIZE)
    previous: NDArray[np.float64] | None = None
    fluxes: list[float] = []
    last = samples.size - _FFT_SIZE + 1
    for index in range(0, last, _FFT_HOP):
        frame = samples[index : index + _FFT_SIZE] * window
        magnitude = np.abs(np.fft.rfft(frame))
        if previous is not None:
            fluxes.append(float(np.sum(np.maximum(magnitude - previous, 0.0))))
        previous = magnitude
    if not fluxes:
        return 0.0
    return float(sum(fluxes) / len(fluxes))


def _run_ffmpeg(
    argv: list[str],
    *,
    timeout_s: float,
    max_stdout_bytes: int,
) -> tuple[bytes, int]:
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
        raise _ExtractError(_EXTRACT_UNAVAILABLE) from error
    except OSError as error:
        raise _ExtractError(_EXTRACT_FAILED) from error
    try:
        stdout, stderr = process.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as error:
        _kill_group(process)
        process.communicate(timeout=5)
        raise _ExtractError(_EXTRACT_TIMEOUT) from error
    _ = (stderr or b"")[:_STDERR_LIMIT]
    if len(stdout) > max_stdout_bytes:
        raise _ExtractError(_EXTRACT_TOO_LARGE)
    return stdout, int(process.returncode or 0)


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        process.kill()
