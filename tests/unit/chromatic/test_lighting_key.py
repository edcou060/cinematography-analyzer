"""Versioned lighting-key estimates from continuous L* evidence."""

from cine_analyzer.application.lighting_key import estimate_lighting_key, lighting_key_confidence
from cine_analyzer.domain.chromatics import LightingKeyLabel, LightnessDistribution
from cine_analyzer.domain.config import LightingKeyRules


def _dist(
    *,
    median: float,
    p10: float,
    p90: float,
    shadow: float,
    highlight: float = 0.0,
) -> LightnessDistribution:
    return LightnessDistribution(
        mean_lstar=median,
        stddev_lstar=1.0,
        p10_lstar=p10,
        p50_lstar=median,
        p90_lstar=p90,
        shadow_ratio=shadow,
        highlight_ratio=highlight,
    )


def test_low_key_requires_dark_median_and_shadow_or_spread() -> None:
    rules = LightingKeyRules()
    label = estimate_lighting_key(
        _dist(median=30.0, p10=5.0, p90=55.0, shadow=0.5),
        rules,
    )
    assert label is LightingKeyLabel.LOW_KEY_ESTIMATE
    assert "ESTIMATE" in label.value
    assert (
        0.0
        < lighting_key_confidence(
            label,
            _dist(median=30.0, p10=5.0, p90=55.0, shadow=0.5),
            rules,
        )
        <= 1.0
    )


def test_low_key_from_spread_without_high_shadow_ratio() -> None:
    rules = LightingKeyRules()
    label = estimate_lighting_key(
        _dist(median=20.0, p10=5.0, p90=80.0, shadow=0.1),
        rules,
    )
    assert label is LightingKeyLabel.LOW_KEY_ESTIMATE


def test_high_key_requires_bright_median_low_shadow_and_limited_spread() -> None:
    rules = LightingKeyRules()
    lightness = _dist(median=80.0, p10=70.0, p90=90.0, shadow=0.02, highlight=0.4)
    assert estimate_lighting_key(lightness, rules) is LightingKeyLabel.HIGH_KEY_ESTIMATE
    assert lighting_key_confidence(LightingKeyLabel.HIGH_KEY_ESTIMATE, lightness, rules) >= 0.5


def test_otherwise_balanced_estimate() -> None:
    rules = LightingKeyRules()
    lightness = _dist(median=50.0, p10=30.0, p90=70.0, shadow=0.2)
    assert estimate_lighting_key(lightness, rules) is LightingKeyLabel.BALANCED_ESTIMATE
    confidence = lighting_key_confidence(
        LightingKeyLabel.BALANCED_ESTIMATE,
        lightness,
        rules,
    )
    assert 0.0 < confidence <= 1.0


def test_bright_high_contrast_is_not_high_key() -> None:
    """A bright frame with a large spread stays balanced; two features are required."""
    rules = LightingKeyRules()
    lightness = _dist(median=80.0, p10=10.0, p90=95.0, shadow=0.02)
    assert estimate_lighting_key(lightness, rules) is LightingKeyLabel.BALANCED_ESTIMATE


def test_low_key_confidence_clips_at_one() -> None:
    rules = LightingKeyRules()
    lightness = _dist(median=0.0, p10=0.0, p90=100.0, shadow=1.0)
    assert lighting_key_confidence(LightingKeyLabel.LOW_KEY_ESTIMATE, lightness, rules) == 1.0


def test_low_key_confidence_clips_at_zero_when_the_median_opposes_the_label() -> None:
    rules = LightingKeyRules(low_median_lstar=0.0)
    lightness = _dist(median=100.0, p10=90.0, p90=100.0, shadow=0.0)
    assert lighting_key_confidence(LightingKeyLabel.LOW_KEY_ESTIMATE, lightness, rules) == 0.0


def test_low_key_confidence_uses_shadow_without_spread_bonus() -> None:
    rules = LightingKeyRules()
    lightness = _dist(median=20.0, p10=10.0, p90=30.0, shadow=0.5)
    confidence = lighting_key_confidence(LightingKeyLabel.LOW_KEY_ESTIMATE, lightness, rules)
    assert 0.0 < confidence < 1.0
