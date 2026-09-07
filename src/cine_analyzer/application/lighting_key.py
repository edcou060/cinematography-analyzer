"""Lighting-key estimate rules. Labels describe sampled pixels, not artistic intent."""

from cine_analyzer.domain.chromatics import LightingKeyLabel, LightnessDistribution
from cine_analyzer.domain.config import LightingKeyRules

__all__ = ["CHROMATIC_METHOD_VERSION", "estimate_lighting_key", "lighting_key_confidence"]

CHROMATIC_METHOD_VERSION = "chromatics-v1"


def estimate_lighting_key(
    lightness: LightnessDistribution,
    rules: LightingKeyRules,
) -> LightingKeyLabel:
    """Apply the versioned thresholds from configuration.

    ``LOW_KEY_ESTIMATE`` when median L* is below the low cutoff and either
    spread or shadow-ratio is high. ``HIGH_KEY_ESTIMATE`` when median L* is
    above the high cutoff, shadows are scarce, and spread is limited.
    Otherwise ``BALANCED_ESTIMATE``.
    """
    spread = lightness.p90_lstar - lightness.p10_lstar
    median = lightness.p50_lstar
    if median < rules.low_median_lstar and (
        spread > rules.low_spread_lstar or lightness.shadow_ratio > rules.low_shadow_ratio
    ):
        return LightingKeyLabel.LOW_KEY_ESTIMATE
    if (
        median > rules.high_median_lstar
        and lightness.shadow_ratio < rules.high_shadow_ratio
        and spread < rules.high_spread_lstar
    ):
        return LightingKeyLabel.HIGH_KEY_ESTIMATE
    return LightingKeyLabel.BALANCED_ESTIMATE


def lighting_key_confidence(
    label: LightingKeyLabel,
    lightness: LightnessDistribution,
    rules: LightingKeyRules,
) -> float:
    """Uncalibrated heuristic in ``[0, 1]``. Distance from the nearest opposing cutoff."""
    spread = lightness.p90_lstar - lightness.p10_lstar
    median = lightness.p50_lstar
    if label is LightingKeyLabel.LOW_KEY_ESTIMATE:
        median_gap = (rules.low_median_lstar - median) / max(rules.low_median_lstar, 1.0)
        extra = 0.15 if spread > rules.low_spread_lstar else 0.0
        extra += 0.15 if lightness.shadow_ratio > rules.low_shadow_ratio else 0.0
        return _clip(0.45 + 0.4 * median_gap + extra)
    if label is LightingKeyLabel.HIGH_KEY_ESTIMATE:
        median_gap = (median - rules.high_median_lstar) / max(100.0 - rules.high_median_lstar, 1.0)
        return _clip(0.5 + 0.4 * median_gap)
    # Balanced: closer to either key rule is less confident.
    low_distance = abs(median - rules.low_median_lstar)
    high_distance = abs(median - rules.high_median_lstar)
    nearest = min(low_distance, high_distance)
    return _clip(0.35 + nearest / 80.0)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))
