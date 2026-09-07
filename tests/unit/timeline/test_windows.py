"""Timeline window alignment: offsets and the last partial window."""

import pytest
from tests.factories import make_shot, make_shot_set

from cine_analyzer.application.normalize import percentile
from cine_analyzer.application.timeline import shot_index_at, window_starts
from cine_analyzer.domain.shots import ShotSet


def test_window_starts_include_the_last_partial_window() -> None:
    assert window_starts(4200, 500) == (0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000)
    assert window_starts(4000, 500)[-1] == 3500
    assert window_starts(499, 500) == (0,)
    assert window_starts(0, 500) == ()
    assert window_starts(1000, 0) == ()


def test_shot_index_at_uses_half_open_ranges() -> None:
    shot_set = make_shot_set(
        shots=(
            make_shot(index=0, start_ms=0, end_ms=2000),
            make_shot(index=1, start_ms=2000, end_ms=4000),
        )
    )
    assert shot_index_at(0, shot_set) == 0
    assert shot_index_at(1999, shot_set) == 0
    assert shot_index_at(2000, shot_set) == 1
    assert shot_index_at(5000, shot_set) == 1


def test_shot_set_factory_is_a_shot_set() -> None:
    assert isinstance(make_shot_set(), ShotSet)


def test_percentile_rejects_an_empty_series() -> None:
    with pytest.raises(ValueError, match="at least one"):
        percentile((), 50.0)


def test_percentile_of_a_single_value_is_that_value() -> None:
    assert percentile((7.0,), 90.0) == 7.0
