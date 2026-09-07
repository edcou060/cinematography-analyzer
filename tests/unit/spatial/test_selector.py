"""Primary-track scoring and stable tie-breaks."""

from uuid import uuid4

from tests.unit.spatial.helpers import box, hit, spatial_config

from cine_analyzer.application.spatial_select import CoverageAreaConfidenceSelector, track_coverage
from cine_analyzer.application.spatial_track import IoUSubjectTracker


def test_higher_coverage_wins_over_a_brief_large_box() -> None:
    a1, a2, a3, b1 = uuid4(), uuid4(), uuid4(), uuid4()
    persistent = (
        hit(a1, box(0.3, 0.3, 0.5, 0.6)),
        hit(a2, box(0.3, 0.3, 0.5, 0.6)),
        hit(a3, box(0.3, 0.3, 0.5, 0.6)),
    )
    brief = hit(b1, box(0.0, 0.0, 0.9, 0.9))
    samples = (a1, a2, a3, b1)
    observed = IoUSubjectTracker().track((*persistent, brief), samples, spatial_config())
    chosen = CoverageAreaConfidenceSelector().select(observed, 4, spatial_config())
    assert chosen == "t0001"


def test_ties_break_by_track_id() -> None:
    left_id, right_id = uuid4(), uuid4()
    hits = (
        hit(left_id, box(0.0, 0.2, 0.3, 0.8)),
        hit(left_id, box(0.7, 0.2, 1.0, 0.8)),
        hit(right_id, box(0.0, 0.2, 0.3, 0.8)),
        hit(right_id, box(0.7, 0.2, 1.0, 0.8)),
    )
    observed = IoUSubjectTracker().track(hits, (left_id, right_id), spatial_config())
    chosen = CoverageAreaConfidenceSelector().select(observed, 2, spatial_config())
    assert chosen == "t0001"


def test_below_coverage_floor_is_not_selected() -> None:
    present, missing_a, missing_b = uuid4(), uuid4(), uuid4()
    observed = IoUSubjectTracker().track(
        (hit(present, box(0.2, 0.2, 0.5, 0.8)),),
        (present, missing_a, missing_b),
        spatial_config(),
    )
    chosen = CoverageAreaConfidenceSelector().select(observed, 3, spatial_config())
    assert chosen is None
    assert track_coverage(observed, 3, "t0001") < 0.40


def test_empty_observations_and_zero_samples_yield_none() -> None:
    selector = CoverageAreaConfidenceSelector()
    config = spatial_config()
    assert selector.select((), 3, config) is None
    sample = uuid4()
    observed = IoUSubjectTracker().track((hit(sample, box(0.2, 0.2, 0.5, 0.8)),), (sample,), config)
    assert selector.select(observed, 0, config) is None
    assert track_coverage(observed, 0, "t0001") == 0.0
