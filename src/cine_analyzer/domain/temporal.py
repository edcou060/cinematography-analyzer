"""Temporal, audio, and tension-proxy components.

The combined tension number is never stored without the parts that produced it.
"""

from typing import Annotated

from pydantic import Field

from cine_analyzer.domain.measurements import Measurement
from cine_analyzer.domain.types import NonNegativeFloat, Score, StrictModel

__all__ = [
    "AudioWindowValue",
    "TemporalMeasurement",
    "TemporalValue",
    "TensionComponents",
]


class TemporalValue(StrictModel):
    """Per-shot duration and motion magnitudes. Camera-movement labels are not emitted."""

    duration_ms: Annotated[
        int,
        Field(gt=0, description="Shot duration, integer milliseconds."),
    ]
    motion_magnitude_median: NonNegativeFloat | None = None
    global_motion_magnitude: NonNegativeFloat | None = None
    residual_motion_magnitude: NonNegativeFloat | None = None
    motion_magnitude_p90: NonNegativeFloat | None = None
    flow_valid_ratio: Score | None = None
    direction_consistency: Score | None = None


class AudioWindowValue(StrictModel):
    """Audio features over one timeline window. Absent audio is a measurement status, not zeros."""

    rms_dbfs: float
    onset_strength: NonNegativeFloat
    spectral_flux: NonNegativeFloat
    loudness_lufs_short_term: float | None = None


class TensionComponents(StrictModel):
    """Named proxy components. Changing the configured weights changes combined_proxy."""

    cut_activity: Score
    audio_activity: Score
    motion_activity: Score
    combined_proxy: Score


TemporalMeasurement = Measurement[TemporalValue]
