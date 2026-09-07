"""Palette ordering, proportion tolerance, and lightness percentile order."""

import pytest
from pydantic import ValidationError
from tests.factories import make_chromatic_value, make_swatch

from cine_analyzer.domain.chromatics import (
    ChromaticValue,
    LabColor,
    LightingKeyLabel,
    LightnessDistribution,
    RgbColor,
)


def test_hex_must_match_the_rgb_channels() -> None:
    with pytest.raises(ValidationError, match="hex must match"):
        RgbColor(r=1, g=2, b=3, hex="#000000")


def test_lowercase_hex_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RgbColor(r=10, g=11, b=12, hex="#0a0b0c")


def test_lab_lstar_is_not_an_eight_bit_channel() -> None:
    with pytest.raises(ValidationError):
        LabColor(lstar=128.0, a=0.0, b=0.0)


def test_percentiles_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="p10 <= p50 <= p90"):
        LightnessDistribution(
            mean_lstar=40.0,
            stddev_lstar=1.0,
            p10_lstar=50.0,
            p50_lstar=40.0,
            p90_lstar=60.0,
            shadow_ratio=0.1,
            highlight_ratio=0.1,
        )


def test_palette_ranks_must_be_contiguous_from_one() -> None:
    with pytest.raises(ValidationError, match="ranks"):
        ChromaticValue(
            palette=(make_swatch(rank=2, proportion=1.0, red=1, green=2, blue=3),),
            lightness=make_chromatic_value().lightness,
            lighting_key=LightingKeyLabel.LOW_KEY_ESTIMATE,
            usable_pixel_ratio=1.0,
        )


def test_palette_proportions_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1"):
        ChromaticValue(
            palette=(
                make_swatch(rank=1, proportion=0.5, red=10, green=10, blue=10),
                make_swatch(rank=2, proportion=0.4, red=20, green=20, blue=20),
            ),
            lightness=make_chromatic_value().lightness,
            lighting_key=LightingKeyLabel.HIGH_KEY_ESTIMATE,
            usable_pixel_ratio=1.0,
        )


def test_palette_must_be_sorted_by_decreasing_proportion_then_hex() -> None:
    with pytest.raises(ValidationError, match="sorted"):
        ChromaticValue(
            palette=(
                make_swatch(rank=1, proportion=0.4, red=10, green=10, blue=10),
                make_swatch(rank=2, proportion=0.6, red=20, green=20, blue=20),
            ),
            lightness=make_chromatic_value().lightness,
            lighting_key=LightingKeyLabel.BALANCED_ESTIMATE,
            usable_pixel_ratio=1.0,
        )


def test_ties_are_broken_by_hex() -> None:
    value = ChromaticValue(
        palette=(
            make_swatch(rank=1, proportion=0.5, red=1, green=1, blue=1),
            make_swatch(rank=2, proportion=0.5, red=2, green=2, blue=2),
        ),
        lightness=make_chromatic_value().lightness,
        lighting_key=LightingKeyLabel.BALANCED_ESTIMATE,
        usable_pixel_ratio=1.0,
    )

    assert value.palette[0].rgb.hex < value.palette[1].rgb.hex


def test_a_valid_palette_is_accepted() -> None:
    value = ChromaticValue(
        palette=(
            make_swatch(rank=1, proportion=0.7, red=8, green=8, blue=8),
            make_swatch(rank=2, proportion=0.3, red=9, green=9, blue=9),
        ),
        lightness=make_chromatic_value().lightness,
        lighting_key=LightingKeyLabel.BALANCED_ESTIMATE,
        usable_pixel_ratio=0.8,
    )

    assert sum(swatch.proportion for swatch in value.palette) == pytest.approx(1.0)
