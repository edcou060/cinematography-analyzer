"""Local edit activity from internal shot boundaries. Not narrative scene density."""

import math

from cine_analyzer.application.normalize import clip01
from cine_analyzer.domain.config import TensionConfig

__all__ = ["cut_activity", "internal_boundary_ms"]


def internal_boundary_ms(starts_ms: tuple[int, ...]) -> tuple[int, ...]:
    """Internal detected boundaries: shot starts after time zero. Clip start is not a cut."""
    return tuple(start for start in starts_ms if start > 0)


def cut_activity(
    at_ms: int,
    boundaries_ms: tuple[int, ...],
    config: TensionConfig,
) -> float:
    """Gaussian kernel density, clipped to ``[0, 1]`` against ``cut_reference``."""
    if not boundaries_ms:
        return 0.0
    sigma = float(config.cut_sigma_ms)
    energy = 0.0
    for boundary in boundaries_ms:
        delta = (at_ms - boundary) / sigma
        energy += math.exp(-0.5 * delta * delta)
    return clip01(energy / config.cut_reference)
