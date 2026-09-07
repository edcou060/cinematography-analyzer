"""TimeRangeMs invariants, including property tests for duration and ordering."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from cine_analyzer.domain.time import Rational, TimeRangeMs


def test_duration_is_end_minus_start() -> None:
    span = TimeRangeMs(start_ms=1_000, end_ms=1_250)

    assert span.duration_ms == 250


def test_a_reversed_range_is_rejected() -> None:
    with pytest.raises(ValidationError, match="end_ms must be greater than start_ms"):
        TimeRangeMs(start_ms=500, end_ms=500)


def test_a_negative_start_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TimeRangeMs(start_ms=-1, end_ms=10)


def test_an_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TimeRangeMs.model_validate({"start_ms": 0, "end_ms": 10, "start_s": 0})


def test_the_range_is_immutable() -> None:
    span = TimeRangeMs(start_ms=0, end_ms=10)

    with pytest.raises(ValidationError, match="frozen"):
        span.start_ms = 1  # type: ignore[misc]


def test_a_zero_denominator_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Rational(numerator=24, denominator=0)


@given(
    start=st.integers(min_value=0, max_value=10_000_000),
    length=st.integers(min_value=1, max_value=1_200_000),
)
def test_any_ordered_bounds_have_exact_integer_duration(start: int, length: int) -> None:
    span = TimeRangeMs(start_ms=start, end_ms=start + length)

    assert span.duration_ms == length
    assert span.end_ms > span.start_ms


@given(
    start=st.integers(min_value=0, max_value=10_000_000),
    end=st.integers(min_value=0, max_value=10_000_000),
)
def test_any_unordered_or_empty_bounds_are_rejected(start: int, end: int) -> None:
    if end > start:
        TimeRangeMs(start_ms=start, end_ms=end)
        return

    with pytest.raises(ValidationError):
        TimeRangeMs(start_ms=start, end_ms=end)
