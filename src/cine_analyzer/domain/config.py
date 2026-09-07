"""Canonical analysis configuration and its hash.

Deployment secrets never belong here. Changing serialization that would invalidate
cache identity requires an ADR.
"""

import hashlib
import json
from typing import Annotated, Final, Self

from pydantic import Field, model_validator

from cine_analyzer.domain.types import SCHEMA_VERSION, Score, StrictModel

__all__ = [
    "DEFAULT_PIPELINE_VERSION",
    "AnalysisConfig",
    "AudioConfig",
    "ChromaticConfig",
    "CriticConfig",
    "FarnebackParams",
    "FramingRules",
    "LightingKeyRules",
    "LimitsConfig",
    "MotionConfig",
    "PrimaryTrackWeights",
    "ShotsConfig",
    "SpatialConfig",
    "TensionConfig",
    "TensionWeights",
    "canonical_hash",
    "canonical_json_bytes",
]

DEFAULT_PIPELINE_VERSION: Final = "0.1.0"
_WEIGHT_SUM_TOLERANCE: Final = 1e-9


def canonical_json_bytes(model: StrictModel) -> bytes:
    """Serialize a model to the byte string that ``canonical_hash`` digests."""
    payload = json.dumps(
        model.model_dump(mode="json", exclude_none=False),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return payload.encode("utf-8")


def canonical_hash(model: StrictModel) -> str:
    """SHA-256 of the canonical JSON form. Key order and formatting do not matter."""
    return hashlib.sha256(canonical_json_bytes(model)).hexdigest()


class LimitsConfig(StrictModel):
    """Acceptance ceilings. Enforced at probe time; part of the hashed analysis key."""

    max_upload_bytes: Annotated[int, Field(gt=0, description="Maximum upload size in bytes.")]
    max_duration_ms: Annotated[
        int,
        Field(gt=0, description="Maximum accepted media duration, integer milliseconds."),
    ]
    max_width: Annotated[int, Field(gt=0)]
    max_height: Annotated[int, Field(gt=0)]


class ShotsConfig(StrictModel):
    """Shot-boundary detector selection, working resolution, and thresholds.

    Thresholds are hashed with the analysis so a detector change cannot reuse
    a previous identity (ADR-0010).
    """

    backend: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    detector: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    min_shot_ms: Annotated[
        int,
        Field(gt=0, description="Minimum accepted shot length, integer milliseconds."),
    ]
    working_width: Annotated[
        int,
        Field(ge=16, le=4096, description="Target decode width in pixels for detection."),
    ] = 320
    threshold: Annotated[
        float,
        Field(
            gt=0,
            description=(
                "Detector threshold. AdaptiveDetector.adaptive_threshold or "
                "ContentDetector.threshold."
            ),
        ),
    ] = 3.0
    min_content_val: Annotated[
        float,
        Field(
            ge=0,
            description="AdaptiveDetector minimum content value. Ignored by content detector.",
        ),
    ] = 15.0
    debug: bool = False


class LightingKeyRules(StrictModel):
    """Versioned lighting-key estimate thresholds. Labels are estimates, not intent."""

    low_median_lstar: Annotated[float, Field(ge=0.0, le=100.0)] = 40.0
    low_spread_lstar: Annotated[float, Field(ge=0.0, le=100.0)] = 45.0
    low_shadow_ratio: Score = 0.40
    high_median_lstar: Annotated[float, Field(ge=0.0, le=100.0)] = 65.0
    high_spread_lstar: Annotated[float, Field(ge=0.0, le=100.0)] = 45.0
    high_shadow_ratio: Score = 0.10


class ChromaticConfig(StrictModel):
    """Sampling, letterbox, clustering, and lighting-key rules (ADR-0011)."""

    samples_per_shot: Annotated[int, Field(ge=1)]
    max_pixels_per_shot: Annotated[int, Field(ge=1)]
    clusters: Annotated[int, Field(ge=1, le=5)]
    random_seed: int
    working_max_side: Annotated[
        int,
        Field(ge=16, le=4096, description="Longest downscale side in pixels before sampling."),
    ] = 640
    kmeans_batch_size: Annotated[int, Field(ge=1)] = 1024
    kmeans_n_init: Annotated[int, Field(ge=1)] = 3
    delta_e_merge: Annotated[
        float,
        Field(ge=0.0, description="CIE76 Delta-E below which palette centres merge."),
    ] = 3.0
    letterbox_lstar_max: Annotated[
        float,
        Field(ge=0.0, le=100.0, description="Maximum CIE L* treated as near-black letterbox."),
    ] = 8.0
    letterbox_coverage: Score = 0.92
    min_usable_pixel_ratio: Score = 0.05
    shadow_lstar: Annotated[float, Field(ge=0.0, le=100.0)] = 20.0
    highlight_lstar: Annotated[float, Field(ge=0.0, le=100.0)] = 80.0
    min_swatch_proportion: Score = 0.02
    lighting_key_rules: LightingKeyRules = LightingKeyRules()


class PrimaryTrackWeights(StrictModel):
    """Primary-subject score weights. They must sum to one (metric-definitions §5.1)."""

    coverage: Score = 0.45
    median_area: Score = 0.35
    median_confidence: Score = 0.20

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> Self:
        total = self.coverage + self.median_area + self.median_confidence
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            message = "primary-track weights must sum to 1"
            raise ValueError(message)
        return self


class FramingRules(StrictModel):
    """Versioned person-height framing estimates. Labels are estimates, not shot size."""

    version: Annotated[str, Field(min_length=1, max_length=64)] = "framing_rules_v1"
    min_track_coverage: Score = 0.40
    extreme_wide_height_max: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.18
    wide_height_max: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.38
    medium_height_max: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.62
    close_up_height_max: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.85
    edge_truncation: Score = 0.02
    disagreement_fraction: Score = 0.40

    @model_validator(mode="after")
    def height_thresholds_increase(self) -> Self:
        ordered = (
            self.extreme_wide_height_max
            < self.wide_height_max
            < self.medium_height_max
            < self.close_up_height_max
        )
        if not ordered:
            message = "framing height thresholds must be strictly increasing"
            raise ValueError(message)
        return self


class SpatialConfig(StrictModel):
    """Spatial-pillar backend, tracking, proximity, and framing rules (ADR-0013, ADR-0014)."""

    backend: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
    checkpoint: str | None = None
    sample_fps: Annotated[
        float,
        Field(gt=0, description="Spatial sampling rate in frames per second."),
    ]
    person_confidence: Score
    thirds_sigma: Annotated[
        float,
        Field(gt=0.0, description="Gaussian width for thirds and center proximity."),
    ] = 0.18
    track_iou_min: Score = 0.30
    primary_track_weights: PrimaryTrackWeights = PrimaryTrackWeights()
    framing_rules: FramingRules = FramingRules()


class FarnebackParams(StrictModel):
    """Dense Farneback hyperparameters. Camera-movement labels are not derived from these."""

    pyr_scale: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.5
    levels: Annotated[int, Field(ge=1, le=8)] = 3
    winsize: Annotated[int, Field(ge=3, le=64)] = 15
    iterations: Annotated[int, Field(ge=1, le=16)] = 3
    poly_n: Annotated[int, Field(ge=5, le=7)] = 5
    poly_sigma: Annotated[float, Field(gt=0.0)] = 1.2


class MotionConfig(StrictModel):
    """Motion sampling and Farneback identity (ADR-0015). Camera-movement labels are not emitted."""

    sample_fps: Annotated[
        float,
        Field(gt=0, description="Motion sampling rate in frames per second."),
    ]
    working_max_side: Annotated[
        int,
        Field(ge=32, le=1920, description="Longest side after aspect-preserving downscale."),
    ] = 320
    discontinuity_diag_per_s: Annotated[
        float,
        Field(
            gt=0.0,
            description=(
                "Flag a pair when global magnitude exceeds this many frame-diagonals per second."
            ),
        ),
    ] = 1.5
    farneback: FarnebackParams = FarnebackParams()


class AudioConfig(StrictModel):
    """Audio resampling target and analysis window (ADR-0016)."""

    sample_rate_hz: Annotated[int, Field(gt=0, description="Target audio sample rate in hertz.")]
    window_ms: Annotated[
        int,
        Field(ge=50, le=10_000, description="Audio feature window, integer milliseconds."),
    ] = 1000


class TensionWeights(StrictModel):
    """Weights of the named tension proxy. They must sum to one."""

    cut_activity: Score
    audio_activity: Score
    motion: Score

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> Self:
        total = self.cut_activity + self.audio_activity + self.motion
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            message = "tension weights must sum to 1"
            raise ValueError(message)
        return self


class TensionConfig(StrictModel):
    """Tension-proxy configuration (ADR-0017). Combined curve always stores weights."""

    weights: TensionWeights
    hop_ms: Annotated[
        int,
        Field(ge=10, le=10_000, description="Timeline hop, integer milliseconds."),
    ] = 500
    cut_sigma_ms: Annotated[
        int,
        Field(
            ge=1,
            le=10_000,
            description="Gaussian cut-activity kernel width, integer milliseconds.",
        ),
    ] = 750
    cut_reference: Annotated[float, Field(gt=0.0)] = 3.0
    percentile_low: Annotated[float, Field(ge=0.0, lt=50.0)] = 10.0
    percentile_high: Annotated[float, Field(gt=50.0, le=100.0)] = 90.0
    epsilon: Annotated[float, Field(gt=0.0)] = 1e-6


class CriticConfig(StrictModel):
    """Interpretation switch. Disabled by default; cannot write a measured field."""

    enabled: bool = False


class AnalysisConfig(StrictModel):
    """The hashed analysis configuration. Environment endpoints never appear here."""

    schema_version: Annotated[str, Field(description="Analysis-config schema version.")] = (
        SCHEMA_VERSION
    )
    pipeline_version: Annotated[str, Field(min_length=1, max_length=64)] = DEFAULT_PIPELINE_VERSION
    limits: LimitsConfig = LimitsConfig(
        max_upload_bytes=1_073_741_824,
        max_duration_ms=1_200_000,
        max_width=4096,
        max_height=2160,
    )
    shots: ShotsConfig = ShotsConfig(
        backend="pyscenedetect",
        detector="adaptive",
        min_shot_ms=300,
    )
    chromatic: ChromaticConfig = ChromaticConfig(
        samples_per_shot=3,
        max_pixels_per_shot=50_000,
        clusters=5,
        random_seed=42,
    )
    spatial: SpatialConfig = SpatialConfig(
        backend="none",
        checkpoint=None,
        sample_fps=2.0,
        person_confidence=0.35,
    )
    motion: MotionConfig = MotionConfig(sample_fps=6.0)
    audio: AudioConfig = AudioConfig(sample_rate_hz=22_050)
    tension: TensionConfig = TensionConfig(
        weights=TensionWeights(cut_activity=0.35, audio_activity=0.30, motion=0.35),
    )
    critic: CriticConfig = CriticConfig(enabled=False)

    @model_validator(mode="after")
    def schema_is_supported(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported analysis-config schema_version {self.schema_version!r}"
            raise ValueError(message)
        return self

    def hash(self) -> str:
        """SHA-256 identity of this configuration."""
        return canonical_hash(self)
