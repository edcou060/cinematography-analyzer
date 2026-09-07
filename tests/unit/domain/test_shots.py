"""Shot sets are ordered, contiguous, and cover the analysed span exactly."""

from itertools import pairwise
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from tests.factories import make_shot, make_shot_set

from cine_analyzer.domain.shots import ShotBoundary, TransitionKind
from cine_analyzer.domain.time import TimeRangeMs


def test_a_single_shot_covers_its_own_duration() -> None:
    shot_set = make_shot_set()

    assert shot_set.duration_ms() == 4000
    assert shot_set.shots[0].time_range.duration_ms == 4000


def test_contiguous_shots_sum_to_the_clip_span() -> None:
    shot_set = make_shot_set(
        shots=(
            make_shot(index=0, start_ms=0, end_ms=1500),
            make_shot(index=1, start_ms=1500, end_ms=4000),
        )
    )

    assert shot_set.duration_ms() == 4000
    assert sum(shot.time_range.duration_ms for shot in shot_set.shots) == 4000


def test_a_gap_between_shots_is_rejected() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        make_shot_set(
            shots=(
                make_shot(index=0, start_ms=0, end_ms=1000),
                make_shot(index=1, start_ms=1001, end_ms=2000),
            )
        )


def test_an_overlap_is_rejected() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        make_shot_set(
            shots=(
                make_shot(index=0, start_ms=0, end_ms=1500),
                make_shot(index=1, start_ms=1000, end_ms=2000),
            )
        )


def test_indices_must_start_at_zero_and_be_contiguous() -> None:
    with pytest.raises(ValidationError, match="contiguous from zero"):
        make_shot_set(
            shots=(
                make_shot(index=1, start_ms=0, end_ms=1000),
                make_shot(index=2, start_ms=1000, end_ms=2000),
            )
        )


def test_duplicate_shot_ids_are_rejected() -> None:
    shot_id = uuid4()
    with pytest.raises(ValidationError, match="unique"):
        make_shot_set(
            shots=(
                make_shot(index=0, start_ms=0, end_ms=1000, shot_id=shot_id),
                make_shot(index=1, start_ms=1000, end_ms=2000, shot_id=shot_id),
            )
        )


def test_an_unsupported_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        make_shot_set(schema_version="2.0")


def test_an_empty_shot_set_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_shot_set(shots=())


def test_a_boundary_cannot_sit_at_the_clip_start() -> None:
    with pytest.raises(ValidationError):
        ShotBoundary(
            boundary_id=uuid4(),
            position_ms=0,
            transition=TransitionKind.CUT,
        )


@given(
    cuts=st.lists(st.integers(min_value=1, max_value=3_999), min_size=0, max_size=8, unique=True),
)
def test_any_partition_of_a_clip_reconciles_exactly(cuts: list[int]) -> None:
    """Domain contiguity is exact. Adapter rounding tolerance is a later-phase concern."""
    bounds = [0, *sorted(cuts), 4000]
    shots = tuple(
        make_shot(index=index, start_ms=start, end_ms=end)
        for index, (start, end) in enumerate(pairwise(bounds))
        if end > start
    )
    shot_set = make_shot_set(shots=shots)

    assert shot_set.duration_ms() == 4000
    assert sum(shot.time_range.duration_ms for shot in shot_set.shots) == 4000
    assert all(
        left.time_range.end_ms == right.time_range.start_ms
        for left, right in pairwise(shot_set.shots)
    )


def test_time_range_unknown_field_on_a_shot_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        TimeRangeMs.model_validate({"start_ms": 0, "end_ms": 10, "duration_seconds": 0.01})
