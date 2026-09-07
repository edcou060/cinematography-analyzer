"""Audio analysis port. FFmpeg and NumPy stay in the adapter."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cine_analyzer.domain.config import AudioConfig
from cine_analyzer.domain.temporal import AudioWindowValue
from cine_analyzer.domain.types import MetricStatus

__all__ = ["AudioAnalyzeResult", "AudioAnalyzer"]


@dataclass(frozen=True, slots=True)
class AudioAnalyzeResult:
    """Windowed features aligned to the caller-supplied starts, or a named absence."""

    status: MetricStatus
    reason_code: str | None
    windows: tuple[AudioWindowValue | None, ...]


class AudioAnalyzer(Protocol):
    """Extract mono PCM and compute window features. Never invoked for no-audio clips."""

    def analyze(
        self,
        source: Path,
        *,
        has_audio: bool,
        duration_ms: int,
        config: AudioConfig,
        window_starts_ms: tuple[int, ...],
    ) -> AudioAnalyzeResult:
        """Return features or NO_AUDIO / UNAVAILABLE. Paths never appear in errors."""
