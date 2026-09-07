"""Chromatic measurements: palettes, lightness, and lighting-key estimates."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from cine_analyzer.domain.measurements import Measurement
from cine_analyzer.domain.types import HexColor, NonNegativeFloat, Score, StrictModel

__all__ = [
    "PALETTE_PROPORTION_TOLERANCE",
    "ChromaticMeasurement",
    "ChromaticValue",
    "ColorSwatch",
    "LabColor",
    "LightingKeyLabel",
    "LightnessDistribution",
    "RgbColor",
]

PALETTE_PROPORTION_TOLERANCE = 1e-6


class LabColor(StrictModel):
    """CIE L*a*b* colour. L* is not an OpenCV 8-bit L channel."""

    lstar: Annotated[
        float,
        Field(ge=0.0, le=100.0, description="CIE L*, range [0, 100]."),
    ]
    a: Annotated[float, Field(ge=-128.0, le=127.0)]
    b: Annotated[float, Field(ge=-128.0, le=127.0)]


class RgbColor(StrictModel):
    """8-bit sRGB plus the matching uppercase hex encoding."""

    r: Annotated[int, Field(ge=0, le=255)]
    g: Annotated[int, Field(ge=0, le=255)]
    b: Annotated[int, Field(ge=0, le=255)]
    hex: HexColor

    @model_validator(mode="after")
    def hex_matches_channels(self) -> Self:
        expected = f"#{self.r:02X}{self.g:02X}{self.b:02X}"
        if self.hex != expected:
            message = "hex must match the r, g, b channels"
            raise ValueError(message)
        return self


class ColorSwatch(StrictModel):
    """One palette entry. Rank 1 is the most prevalent colour."""

    rank: Annotated[int, Field(ge=1, le=5)]
    lab: LabColor
    rgb: RgbColor
    proportion: Score


class LightingKeyLabel(StrEnum):
    """Heuristic lighting-key estimate. Describes sampled pixels, not intent."""

    LOW_KEY_ESTIMATE = "LOW_KEY_ESTIMATE"
    HIGH_KEY_ESTIMATE = "HIGH_KEY_ESTIMATE"
    BALANCED_ESTIMATE = "BALANCED_ESTIMATE"


class LightnessDistribution(StrictModel):
    """Perceptual lightness statistics in CIE L*."""

    mean_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    stddev_lstar: NonNegativeFloat
    p10_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    p50_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    p90_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    shadow_ratio: Score
    highlight_ratio: Score

    @model_validator(mode="after")
    def percentiles_are_ordered(self) -> Self:
        if not (self.p10_lstar <= self.p50_lstar <= self.p90_lstar):
            message = "lightness percentiles must satisfy p10 <= p50 <= p90"
            raise ValueError(message)
        return self


class ChromaticValue(StrictModel):
    """Measured palette and lightness, plus a lighting-key estimate."""

    palette: Annotated[tuple[ColorSwatch, ...], Field(min_length=1, max_length=5)]
    lightness: LightnessDistribution
    lighting_key: LightingKeyLabel
    usable_pixel_ratio: Score

    @model_validator(mode="after")
    def palette_is_ranked_and_complete(self) -> Self:
        ranks = [swatch.rank for swatch in self.palette]
        expected_ranks = list(range(1, len(self.palette) + 1))
        if ranks != expected_ranks:
            message = "palette ranks must be contiguous from 1 in display order"
            raise ValueError(message)
        total = sum(swatch.proportion for swatch in self.palette)
        if abs(total - 1.0) > PALETTE_PROPORTION_TOLERANCE:
            message = "palette proportions must sum to 1 within tolerance"
            raise ValueError(message)
        ordered = sorted(self.palette, key=lambda swatch: (-swatch.proportion, swatch.rgb.hex))
        observed = [(swatch.proportion, swatch.rgb.hex) for swatch in self.palette]
        expected = [(swatch.proportion, swatch.rgb.hex) for swatch in ordered]
        if observed != expected:
            message = "palette must be sorted by decreasing proportion, then by hex for ties"
            raise ValueError(message)
        return self


ChromaticMeasurement = Measurement[ChromaticValue]
