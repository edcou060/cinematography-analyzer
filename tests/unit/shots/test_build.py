"""Shot interval construction: outer bounds, merge policy, deterministic ids."""

from datetime import UTC, datetime
from uuid import UUID

from tests.factories import DIGEST, make_provenance

from cine_analyzer.application.identity import stable_uuid
from cine_analyzer.application.shots import boundaries_to_shot_set, merge_short_ranges
from cine_analyzer.domain.shots import TransitionKind
from cine_analyzer.domain.time import TimeRangeMs
from cine_analyzer.ports.shots import DetectedBoundary

ANALYSIS_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
STAMP = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def test_no_internal_boundary_returns_one_shot_covering_the_clip() -> None:
    shot_set = boundaries_to_shot_set(
        (),
        analysis_id=ANALYSIS_ID,
        duration_ms=4000,
        min_shot_ms=300,
        provenance=make_provenance(),
    )

    assert len(shot_set.shots) == 1
    assert shot_set.shots[0].time_range.start_ms == 0
    assert shot_set.shots[0].time_range.end_ms == 4000
    assert shot_set.shots[0].incoming_boundary_id is None
    assert shot_set.shots[0].outgoing_boundary_id is None
    assert shot_set.shots[0].shot_id == stable_uuid(str(ANALYSIS_ID), "shot", "0")


def test_a_cut_splits_the_clip_into_contiguous_shots() -> None:
    shot_set = boundaries_to_shot_set(
        (DetectedBoundary(position_ms=2000, transition=TransitionKind.CUT, detector_score=1.0),),
        analysis_id=ANALYSIS_ID,
        duration_ms=4000,
        min_shot_ms=300,
        provenance=make_provenance(),
    )

    assert [shot.time_range.start_ms for shot in shot_set.shots] == [0, 2000]
    assert [shot.time_range.end_ms for shot in shot_set.shots] == [2000, 4000]
    assert shot_set.shots[0].outgoing_boundary_id == shot_set.shots[1].incoming_boundary_id
    assert shot_set.duration_ms() == 4000


def test_short_shots_merge_into_the_following_neighbour() -> None:
    merged = merge_short_ranges(
        (
            TimeRangeMs(start_ms=0, end_ms=100),
            TimeRangeMs(start_ms=100, end_ms=2000),
            TimeRangeMs(start_ms=2000, end_ms=4000),
        ),
        min_shot_ms=300,
    )

    assert [(item.start_ms, item.end_ms) for item in merged] == [(0, 2000), (2000, 4000)]


def test_a_short_final_shot_merges_into_the_previous() -> None:
    merged = merge_short_ranges(
        (
            TimeRangeMs(start_ms=0, end_ms=3500),
            TimeRangeMs(start_ms=3500, end_ms=3600),
        ),
        min_shot_ms=300,
    )

    assert [(item.start_ms, item.end_ms) for item in merged] == [(0, 3600)]


def test_cuts_at_zero_or_duration_are_ignored() -> None:
    shot_set = boundaries_to_shot_set(
        (
            DetectedBoundary(position_ms=0, transition=TransitionKind.CUT, detector_score=None),
            DetectedBoundary(position_ms=4000, transition=TransitionKind.CUT, detector_score=None),
            DetectedBoundary(position_ms=4000, transition=TransitionKind.CUT, detector_score=None),
        ),
        analysis_id=ANALYSIS_ID,
        duration_ms=4000,
        min_shot_ms=300,
        provenance=make_provenance(),
    )

    assert len(shot_set.shots) == 1


def test_duplicate_cut_positions_are_collapsed() -> None:
    shot_set = boundaries_to_shot_set(
        (
            DetectedBoundary(position_ms=1500, transition=TransitionKind.CUT, detector_score=0.2),
            DetectedBoundary(position_ms=1500, transition=TransitionKind.CUT, detector_score=0.9),
        ),
        analysis_id=ANALYSIS_ID,
        duration_ms=4000,
        min_shot_ms=300,
        provenance=make_provenance(),
    )

    assert len(shot_set.shots) == 2
    assert shot_set.shots[0].time_range.end_ms == 1500


def test_a_single_short_interval_is_kept() -> None:
    merged = merge_short_ranges((TimeRangeMs(start_ms=0, end_ms=100),), min_shot_ms=300)
    assert [(item.start_ms, item.end_ms) for item in merged] == [(0, 100)]


def test_consecutive_short_shots_collapse_into_the_long_neighbour() -> None:
    merged = merge_short_ranges(
        (
            TimeRangeMs(start_ms=0, end_ms=50),
            TimeRangeMs(start_ms=50, end_ms=80),
            TimeRangeMs(start_ms=80, end_ms=4000),
        ),
        min_shot_ms=300,
    )
    assert [(item.start_ms, item.end_ms) for item in merged] == [(0, 4000)]


def test_ids_are_stable_across_calls() -> None:
    first = boundaries_to_shot_set(
        (DetectedBoundary(position_ms=2000, transition=TransitionKind.CUT, detector_score=None),),
        analysis_id=ANALYSIS_ID,
        duration_ms=4000,
        min_shot_ms=300,
        provenance=make_provenance(config_hash=DIGEST, started_at=STAMP, completed_at=STAMP),
    )
    second = boundaries_to_shot_set(
        (DetectedBoundary(position_ms=2000, transition=TransitionKind.CUT, detector_score=None),),
        analysis_id=ANALYSIS_ID,
        duration_ms=4000,
        min_shot_ms=300,
        provenance=make_provenance(config_hash=DIGEST, started_at=STAMP, completed_at=STAMP),
    )

    assert first.shots[0].shot_id == second.shots[0].shot_id
    assert first.shots[0].outgoing_boundary_id == second.shots[0].outgoing_boundary_id
