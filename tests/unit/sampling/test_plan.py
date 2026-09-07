"""Deterministic sample plans: purposes, dedup, order, and ids."""

from tests.factories import ANALYSIS_ID, VIDEO_ID, make_shot, make_shot_set

from cine_analyzer.application.identity import stable_uuid
from cine_analyzer.application.sampling import frame_duration_ms, plan_samples
from cine_analyzer.domain.config import AnalysisConfig, ChromaticConfig
from cine_analyzer.domain.media import SamplePurpose
from cine_analyzer.domain.time import Rational


def test_frame_duration_ms_rounds_half_up() -> None:
    assert frame_duration_ms(Rational(numerator=25, denominator=1)) == 40
    assert frame_duration_ms(Rational(numerator=1, denominator=1)) == 1000


def test_identical_timestamps_merge_purposes_and_keep_stable_ids() -> None:
    shot_set = make_shot_set(
        shots=(
            make_shot(index=0, start_ms=0, end_ms=2000),
            make_shot(index=1, start_ms=2000, end_ms=4000),
        )
    )
    config = AnalysisConfig()
    first = plan_samples(
        shot_set,
        video_id=VIDEO_ID,
        config=config,
        frame_rate=Rational(numerator=25, denominator=1),
    )
    second = plan_samples(
        shot_set,
        video_id=VIDEO_ID,
        config=config,
        frame_rate=Rational(numerator=25, denominator=1),
    )

    assert first.requests == second.requests
    assert first.analysis_id == ANALYSIS_ID
    timestamps = [request.requested_ms for request in first.requests]
    assert timestamps == sorted(timestamps)
    assert all(request.purposes for request in first.requests)
    evidence = [request for request in first.requests if SamplePurpose.EVIDENCE in request.purposes]
    assert len(evidence) == 2
    sample = first.requests[0]
    assert sample.sample_id == stable_uuid(
        str(ANALYSIS_ID), "sample", str(sample.shot_id), str(sample.requested_ms)
    )
    chromatic = [
        request for request in first.requests if SamplePurpose.CHROMATIC in request.purposes
    ]
    assert len(chromatic) >= 2
    composition = [
        request for request in first.requests if SamplePurpose.COMPOSITION in request.purposes
    ]
    motion = [request for request in first.requests if SamplePurpose.MOTION in request.purposes]
    assert composition
    assert motion


def test_a_very_short_shot_still_gets_one_representative() -> None:
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=80),))
    plan = plan_samples(
        shot_set,
        video_id=VIDEO_ID,
        config=AnalysisConfig(),
        frame_rate=Rational(numerator=25, denominator=1),
    )

    assert plan.requests
    assert all(0 <= request.requested_ms < 80 for request in plan.requests)
    assert any(SamplePurpose.EVIDENCE in request.purposes for request in plan.requests)


def test_non_default_chromatic_count_spaces_targets_evenly() -> None:
    dumped = AnalysisConfig().model_dump(mode="json")
    dumped["chromatic"] = {**dumped["chromatic"], "samples_per_shot": 1}
    config = AnalysisConfig.model_validate(dumped)
    assert config.chromatic == ChromaticConfig.model_validate(dumped["chromatic"])
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=4000),))
    plan = plan_samples(
        shot_set,
        video_id=VIDEO_ID,
        config=config,
        frame_rate=Rational(numerator=25, denominator=1),
    )
    chromatic_times = [
        request.requested_ms
        for request in plan.requests
        if SamplePurpose.CHROMATIC in request.purposes
    ]
    assert chromatic_times == [2000]


def test_requests_stay_inside_each_shot() -> None:
    shot_set = make_shot_set(
        shots=(
            make_shot(index=0, start_ms=0, end_ms=1500),
            make_shot(index=1, start_ms=1500, end_ms=4000),
        )
    )
    plan = plan_samples(
        shot_set,
        video_id=VIDEO_ID,
        config=AnalysisConfig(),
        frame_rate=Rational(numerator=25, denominator=1),
    )
    by_shot = {shot.shot_id: shot for shot in shot_set.shots}
    for request in plan.requests:
        shot = by_shot[request.shot_id]
        assert shot.time_range.start_ms <= request.requested_ms < shot.time_range.end_ms


def test_duplicate_purposes_at_the_same_timestamp_are_kept_once() -> None:
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=2),))
    plan = plan_samples(
        shot_set,
        video_id=VIDEO_ID,
        config=AnalysisConfig(),
        frame_rate=Rational(numerator=25, denominator=1),
    )
    chromatic = [
        request for request in plan.requests if SamplePurpose.CHROMATIC in request.purposes
    ]
    assert chromatic
    assert all(len(request.purposes) == len(set(request.purposes)) for request in plan.requests)
