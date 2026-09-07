"""Retry backoff is bounded and uses jitter."""

from random import Random

from cine_analyzer.worker.retry import retry_countdown_seconds


def test_backoff_doubles_until_the_cap() -> None:
    rng = Random(0)
    first = retry_countdown_seconds(1, base_ms=1000, cap_ms=8000, rng=rng)
    rng = Random(0)
    second = retry_countdown_seconds(2, base_ms=1000, cap_ms=8000, rng=rng)
    rng = Random(0)
    capped = retry_countdown_seconds(8, base_ms=1000, cap_ms=4000, rng=rng)
    assert 1.0 <= first <= 1.1
    assert 2.0 <= second <= 2.2
    assert 4.0 <= capped <= 4.4


def test_attempt_below_one_uses_the_base_delay() -> None:
    delay = retry_countdown_seconds(0, base_ms=500, cap_ms=500, jitter_ratio=0.0, rng=Random(1))
    assert delay == 0.5


def test_unseeded_rng_still_returns_a_positive_delay() -> None:
    delay = retry_countdown_seconds(1, base_ms=100, cap_ms=100, jitter_ratio=0.0)
    assert delay == 0.1
