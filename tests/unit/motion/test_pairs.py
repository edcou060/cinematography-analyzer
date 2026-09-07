"""Motion pairing stays inside one shot and degrades when pairs are missing."""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from tests.factories import (
    ANALYSIS_ID,
    SAMPLE_ID,
    SHOT_ID,
    VIDEO_ID,
    make_artifact,
    make_provenance,
    make_shot,
)
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.motion import (
    adjacent_motion_pairs,
    attach_subject_boxes,
    collect_motion_frames,
    summarize_shot_motion,
)
from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleRequest,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
)
from cine_analyzer.domain.spatial import BoxNorm, SubjectObservation
from cine_analyzer.domain.types import SCHEMA_VERSION
from cine_analyzer.ports.motion import FlowPairStats, MotionFrame, MotionPairInput


def _frame(decoded_ms: int, sample_id: UUID | None = None) -> MotionFrame:
    return MotionFrame(
        sample_id=sample_id or uuid4(),
        jpeg=b"\xff\xd8xx",
        decoded_ms=decoded_ms,
    )


def _stats(**overrides: object) -> FlowPairStats:
    payload: dict[str, object] = {
        "sample_id_a": uuid4(),
        "sample_id_b": uuid4(),
        "dt_ms": 160,
        "at_ms": 80,
        "global_dx": 1.0,
        "global_dy": 0.0,
        "global_magnitude": 0.2,
        "residual_magnitude_median": 0.1,
        "residual_magnitude_p90": 0.15,
        "valid_ratio": 0.8,
        "flagged_discontinuity": False,
    }
    payload.update(overrides)
    return FlowPairStats(**payload)  # type: ignore[arg-type]


def test_adjacent_pairs_never_include_a_non_positive_dt() -> None:
    first = _frame(1000)
    same = _frame(1000)
    later = _frame(1160)
    pairs = adjacent_motion_pairs((first, same, later))
    assert len(pairs) == 1
    assert pairs[0].sample_id_a == same.sample_id
    assert pairs[0].dt_ms == 160
    assert pairs[0].at_ms == 1080


def test_summarize_without_pairs_keeps_duration_and_drops_magnitudes() -> None:
    shot = make_shot()
    result = summarize_shot_motion(
        duration_ms=shot.time_range.duration_ms,
        shot_index=0,
        pairs=(),
        evidence_sample_ids=(),
        method=make_provenance(method="motion.opencv_farneback"),
    )
    assert result.measurement.value is not None
    assert result.measurement.value.duration_ms == 4000
    assert result.measurement.value.global_motion_magnitude is None
    assert result.series == ()
    assert result.flagged_discontinuity is False


def test_flagged_pairs_are_excluded_from_the_median_but_recorded() -> None:
    clean = _stats(
        global_magnitude=0.1, residual_magnitude_median=0.05, flagged_discontinuity=False
    )
    jump = _stats(global_magnitude=4.0, residual_magnitude_median=3.0, flagged_discontinuity=True)
    result = summarize_shot_motion(
        duration_ms=1000,
        shot_index=0,
        pairs=(clean, jump),
        evidence_sample_ids=(SAMPLE_ID,),
        method=make_provenance(),
    )
    assert result.measurement.value is not None
    assert result.measurement.value.global_motion_magnitude == 0.1
    assert result.flagged_discontinuity is True
    assert len(result.series) == 1


def test_direction_consistency_is_one_for_aligned_vectors() -> None:
    left = _stats(global_dx=2.0, global_dy=0.0)
    right = _stats(global_dx=4.0, global_dy=0.0, at_ms=240)
    result = summarize_shot_motion(
        duration_ms=1000,
        shot_index=0,
        pairs=(left, right),
        evidence_sample_ids=(),
        method=make_provenance(),
    )
    assert result.measurement.value is not None
    assert result.measurement.value.direction_consistency == 1.0


def test_zero_global_vectors_score_zero_consistency() -> None:
    left = _stats(global_dx=0.0, global_dy=0.0)
    right = _stats(global_dx=1.0, global_dy=0.0, at_ms=240)
    result = summarize_shot_motion(
        duration_ms=1000,
        shot_index=0,
        pairs=(left, right),
        evidence_sample_ids=(),
        method=make_provenance(),
    )
    assert result.measurement.value is not None
    assert result.measurement.value.direction_consistency == 0.0


def test_attach_subject_boxes_unions_both_samples() -> None:
    pair = MotionPairInput(
        sample_id_a=SAMPLE_ID,
        sample_id_b=uuid4(),
        jpeg_a=b"a",
        jpeg_b=b"b",
        dt_ms=160,
        at_ms=80,
        subject_boxes=(),
    )
    box = BoxNorm(x_min=0.1, y_min=0.1, x_max=0.4, y_max=0.5)
    observation = SubjectObservation(
        track_id="t1",
        sample_id=SAMPLE_ID,
        class_name="person",
        detector_confidence=0.9,
        box=box,
        centroid_x=0.25,
        centroid_y=0.3,
    )
    attached = attach_subject_boxes(pair, (observation,))
    assert attached.subject_boxes == (box,)


def test_collect_motion_frames_skips_missing_timestamps(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    blob = store.put_bytes(b"\xff\xd8xx", storage_key="aa/" + "a" * 64)
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        requests=(
            SampleRequest(
                sample_id=SAMPLE_ID,
                shot_id=SHOT_ID,
                requested_ms=200,
                purposes=(SamplePurpose.MOTION,),
            ),
        ),
    )
    decoded = SampleResult(
        sample_id=SAMPLE_ID,
        shot_id=SHOT_ID,
        requested_ms=200,
        decoded_ms=200,
        purposes=(SamplePurpose.MOTION,),
        status=SampleStatus.DECODED,
        image=make_artifact(),
    )
    manifest = SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(decoded,),
    )
    frames = collect_motion_frames(manifest, {SAMPLE_ID: blob.storage_key}, store, SHOT_ID)
    assert len(frames) == 1
    assert frames[0].decoded_ms == 200
    missing = collect_motion_frames(manifest, {}, store, SHOT_ID)
    assert missing == ()


def test_collect_skips_a_decoded_sample_without_a_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore(tmp_path)
    extra = uuid4()

    def _fake_load(*_args: object, **_kwargs: object) -> tuple[tuple[object, bytes], ...]:
        return ((extra, b"\xff\xd8xx"),)

    monkeypatch.setattr("cine_analyzer.application.motion.load_decoded_jpegs", _fake_load)
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        requests=(),
    )
    manifest = SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(),
    )
    assert collect_motion_frames(manifest, {}, store, SHOT_ID) == ()


def test_even_pair_count_averages_the_median() -> None:
    left = _stats(global_magnitude=0.2, residual_magnitude_median=0.2, residual_magnitude_p90=0.3)
    right = _stats(
        global_magnitude=0.4,
        residual_magnitude_median=0.4,
        residual_magnitude_p90=0.5,
        at_ms=240,
    )
    result = summarize_shot_motion(
        duration_ms=1000,
        shot_index=0,
        pairs=(left, right),
        evidence_sample_ids=(),
        method=make_provenance(),
    )
    assert result.measurement.value is not None
    assert result.measurement.value.global_motion_magnitude == pytest.approx(0.3)
    assert result.measurement.value.residual_motion_magnitude == pytest.approx(0.3)
