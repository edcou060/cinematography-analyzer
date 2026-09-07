"""Audio window features without invoking FFmpeg."""

from pathlib import Path

import numpy as np

from cine_analyzer.adapters.media.ffmpeg_audio import FfmpegAudioExtractor, window_features
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.audio import AudioAnalyzeResult


def test_window_features_are_finite_and_omit_lufs() -> None:
    rate = 22050
    tone = np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    value = window_features(
        tone,
        sample_rate_hz=rate,
        start_ms=0,
        window_ms=1000,
        duration_ms=1000,
    )
    assert value.loudness_lufs_short_term is None
    assert value.onset_strength >= 0.0
    assert value.spectral_flux >= 0.0
    assert value.rms_dbfs < 0.0


def test_empty_or_short_windows_are_defined() -> None:
    empty = window_features(
        np.zeros(0),
        sample_rate_hz=22050,
        start_ms=0,
        window_ms=500,
        duration_ms=500,
    )
    assert empty.rms_dbfs == -120.0
    assert empty.spectral_flux == 0.0
    short = window_features(
        np.zeros(64),
        sample_rate_hz=22050,
        start_ms=0,
        window_ms=500,
        duration_ms=500,
    )
    assert short.spectral_flux == 0.0


def test_exactly_one_fft_frame_has_zero_spectral_flux() -> None:
    value = window_features(
        np.ones(512),
        sample_rate_hz=512,
        start_ms=0,
        window_ms=1000,
        duration_ms=1000,
    )
    assert value.spectral_flux == 0.0
    assert value.onset_strength == 0.0


def test_no_audio_does_not_open_the_source(tmp_path: Path) -> None:
    extractor = FfmpegAudioExtractor("ffmpeg", timeout_ms=1000, max_stdout_bytes=1024)
    result = extractor.analyze(
        tmp_path / "missing.mp4",
        has_audio=False,
        duration_ms=1000,
        config=AnalysisConfig().audio,
        window_starts_ms=(0, 500),
    )
    assert result.status is MetricStatus.NO_AUDIO
    assert result.reason_code == "no_audio_stream"
    assert result.windows == (None, None)


def test_audio_analyze_result_failed_has_no_windows() -> None:
    result = AudioAnalyzeResult(
        status=MetricStatus.FAILED,
        reason_code="audio_extract_failed",
        windows=(None,),
    )
    assert result.windows == (None,)
