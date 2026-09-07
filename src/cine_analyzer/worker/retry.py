"""Bounded exponential backoff with jitter for retryable stage failures."""

from random import Random

__all__ = ["retry_countdown_seconds"]


def retry_countdown_seconds(
    attempt: int,
    *,
    base_ms: int,
    cap_ms: int,
    jitter_ratio: float = 0.1,
    rng: Random | None = None,
) -> float:
    """Seconds until the next attempt. ``attempt`` is the failed attempt number (>=1)."""
    safe_attempt = 1 if attempt < 1 else attempt
    shift = min(safe_attempt - 1, 30)
    delay_ms = min(cap_ms, base_ms * (1 << shift))
    generator = Random() if rng is None else rng
    jitter_ms = delay_ms * jitter_ratio * generator.random()
    return (delay_ms + jitter_ms) / 1000.0
