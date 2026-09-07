"""Robust within-clip normalization. Constant series are defined (ADR-0017)."""

import math

__all__ = ["clip01", "percentile", "robust_normalize"]


def clip01(value: float) -> float:
    """Clamp a finite value into ``[0, 1]``. Non-finite values become 0."""
    if not math.isfinite(value):
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def percentile(values: tuple[float, ...], q: float) -> float:
    """Linear interpolation percentile. ``q`` is in ``[0, 100]``."""
    if not values:
        message = "percentile requires at least one value"
        raise ValueError(message)
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (q / 100.0) * (len(ordered) - 1)
    low_index = int(rank)
    high_index = min(low_index + 1, len(ordered) - 1)
    frac = rank - low_index
    return ordered[low_index] * (1.0 - frac) + ordered[high_index] * frac


def robust_normalize(
    values: tuple[float, ...],
    *,
    percentile_low: float,
    percentile_high: float,
    epsilon: float,
) -> tuple[float, ...]:
    """``N(x)=clip((x-p_low)/(p_high-p_low+ε), 0, 1)``. Constants map to 0."""
    if not values:
        return ()
    low = percentile(values, percentile_low)
    high = percentile(values, percentile_high)
    scale = high - low + epsilon
    return tuple(clip01((value - low) / scale) for value in values)
