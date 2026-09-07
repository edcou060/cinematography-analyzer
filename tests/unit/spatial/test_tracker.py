"""Within-shot tracking resets at the shot boundary (a new track() call)."""

from uuid import uuid4

from tests.unit.spatial.helpers import box, hit, spatial_config

from cine_analyzer.application.spatial_track import IoUSubjectTracker


def test_overlapping_hits_keep_one_track_id() -> None:
    sample_a = uuid4()
    sample_b = uuid4()
    first = hit(sample_a, box(0.2, 0.2, 0.5, 0.8))
    second = hit(sample_b, box(0.22, 0.22, 0.52, 0.82))
    tracked = IoUSubjectTracker().track(
        (first, second),
        (sample_a, sample_b),
        spatial_config(),
    )
    assert len(tracked) == 2
    assert tracked[0].track_id == tracked[1].track_id == "t0001"


def test_separated_hits_open_a_new_track() -> None:
    sample_a = uuid4()
    sample_b = uuid4()
    left = hit(sample_a, box(0.0, 0.2, 0.2, 0.8))
    right = hit(sample_b, box(0.7, 0.2, 0.95, 0.8))
    tracked = IoUSubjectTracker().track((left, right), (sample_a, sample_b), spatial_config())
    assert {item.track_id for item in tracked} == {"t0001", "t0002"}


def test_a_new_call_resets_track_identity() -> None:
    sample = uuid4()
    tracker = IoUSubjectTracker()
    config = spatial_config()
    first = tracker.track((hit(sample, box(0.2, 0.2, 0.5, 0.8)),), (sample,), config)
    second = tracker.track((hit(sample, box(0.2, 0.2, 0.5, 0.8)),), (sample,), config)
    assert first[0].track_id == second[0].track_id == "t0001"


def test_non_person_and_low_confidence_are_dropped() -> None:
    sample = uuid4()
    tracked = IoUSubjectTracker().track(
        (
            hit(sample, box(0.1, 0.1, 0.4, 0.4), class_name="bicycle"),
            hit(sample, box(0.2, 0.2, 0.5, 0.5), confidence=0.1),
        ),
        (sample,),
        spatial_config(person_confidence=0.35),
    )
    assert tracked == ()


def test_hits_for_unknown_samples_are_ignored() -> None:
    known, unknown = uuid4(), uuid4()
    tracked = IoUSubjectTracker().track(
        (hit(unknown, box(0.2, 0.2, 0.5, 0.8)),),
        (known,),
        spatial_config(),
    )
    assert tracked == ()


def test_two_people_in_one_frame_keep_distinct_tracks() -> None:
    sample_a, sample_b = uuid4(), uuid4()
    hits = (
        hit(sample_a, box(0.0, 0.2, 0.3, 0.8)),
        hit(sample_a, box(0.7, 0.2, 1.0, 0.8)),
        hit(sample_b, box(0.0, 0.2, 0.3, 0.8)),
        hit(sample_b, box(0.7, 0.2, 1.0, 0.8)),
    )
    tracked = IoUSubjectTracker().track(hits, (sample_a, sample_b), spatial_config())
    left = {item.track_id for item in tracked if item.box.x_min < 0.5}
    right = {item.track_id for item in tracked if item.box.x_min >= 0.5}
    assert len(left) == 1
    assert len(right) == 1
    assert left != right


def test_already_assigned_tracks_and_hits_are_skipped() -> None:
    sample_a, sample_b = uuid4(), uuid4()
    hits = (
        hit(sample_a, box(0.2, 0.2, 0.5, 0.8)),
        hit(sample_b, box(0.2, 0.2, 0.5, 0.8)),
        hit(sample_b, box(0.22, 0.22, 0.52, 0.82)),
        hit(sample_a, box(0.6, 0.2, 0.9, 0.8)),
        hit(sample_b, box(0.55, 0.2, 0.85, 0.8)),
    )
    tracked = IoUSubjectTracker().track(hits, (sample_a, sample_b), spatial_config())
    assert {item.track_id for item in tracked} >= {"t0001"}
    assert len(tracked) == 5
