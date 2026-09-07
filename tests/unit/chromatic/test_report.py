"""Report aggregation, chromatic wrapping, and frame collection."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from tests.factories import (
    ANALYSIS_ID,
    SAMPLE_ID,
    SHOT_ID,
    make_artifact,
    make_ok_chromatic,
    make_provenance,
    make_shot,
    make_shot_set,
    make_unavailable_spatial,
)
from tests.unit.application.fakes import (
    FakeRepository,
    MemoryStore,
    make_run_report_stages,
    tiny_config,
    video_record_from_bytes,
)
from tests.unit.spatial.helpers import fake_analyzer

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.chromatics import collect_shot_frames, wrap_chromatic_measurement
from cine_analyzer.application.errors import AdapterError, IngestError
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.application.report import (
    assemble_report,
    chromatic_availability,
    video_summary,
)
from cine_analyzer.domain.chromatics import ChromaticMeasurement
from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleRequest,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
)
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.types import SCHEMA_VERSION, MetricStatus
from cine_analyzer.ports.chromatics import ChromaticComputeResult, ChromaticFrame
from cine_analyzer.ports.shots import DecodedSample, DetectionResult


def test_wrap_ok_and_insufficient_measurements() -> None:
    method = make_provenance(method="chromatics.opencv_sklearn")
    ok = ChromaticComputeResult(
        status=MetricStatus.OK,
        value=make_ok_chromatic().value,
        confidence=0.7,
        reason_code=None,
        evidence_sample_ids=(SAMPLE_ID,),
    )
    wrapped = wrap_chromatic_measurement(ok, method=method)
    assert wrapped.status is MetricStatus.OK
    assert wrapped.confidence == 0.7
    missing = wrap_chromatic_measurement(
        ChromaticComputeResult(
            status=MetricStatus.INSUFFICIENT_DATA,
            value=None,
            confidence=None,
            reason_code=None,
            evidence_sample_ids=(),
        ),
        method=method,
    )
    assert missing.reason_code == "chromatic_unavailable"


def test_collect_shot_frames_skips_unavailable_and_other_purposes(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    jpeg = b"\xff\xd8fake"
    blob = store.put_bytes(jpeg, storage_key="aa/" + "a" * 64)
    evidence_id = uuid4()
    unavailable_id = uuid4()
    missing_key_id = uuid4()
    other_shot_id = uuid4()
    other_shot_sample = uuid4()
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=SHOT_ID,
        method_version="sampling-v1",
        requests=(
            SampleRequest(
                sample_id=SAMPLE_ID,
                shot_id=SHOT_ID,
                requested_ms=100,
                purposes=(SamplePurpose.CHROMATIC,),
            ),
            SampleRequest(
                sample_id=evidence_id,
                shot_id=SHOT_ID,
                requested_ms=200,
                purposes=(SamplePurpose.EVIDENCE,),
            ),
            SampleRequest(
                sample_id=unavailable_id,
                shot_id=SHOT_ID,
                requested_ms=300,
                purposes=(SamplePurpose.CHROMATIC,),
            ),
            SampleRequest(
                sample_id=missing_key_id,
                shot_id=SHOT_ID,
                requested_ms=400,
                purposes=(SamplePurpose.CHROMATIC,),
            ),
            SampleRequest(
                sample_id=other_shot_sample,
                shot_id=other_shot_id,
                requested_ms=500,
                purposes=(SamplePurpose.CHROMATIC,),
            ),
        ),
    )
    manifest = SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=SHOT_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(
            SampleResult(
                sample_id=SAMPLE_ID,
                shot_id=SHOT_ID,
                requested_ms=100,
                decoded_ms=120,
                purposes=(SamplePurpose.CHROMATIC,),
                status=SampleStatus.DECODED,
                image=make_artifact(),
            ),
            SampleResult(
                sample_id=evidence_id,
                shot_id=SHOT_ID,
                requested_ms=200,
                decoded_ms=200,
                purposes=(SamplePurpose.EVIDENCE,),
                status=SampleStatus.DECODED,
                image=make_artifact(),
            ),
            SampleResult(
                sample_id=unavailable_id,
                shot_id=SHOT_ID,
                requested_ms=300,
                purposes=(SamplePurpose.CHROMATIC,),
                status=SampleStatus.UNAVAILABLE,
                unavailable_reason="missing",
            ),
            SampleResult(
                sample_id=missing_key_id,
                shot_id=SHOT_ID,
                requested_ms=400,
                decoded_ms=400,
                purposes=(SamplePurpose.CHROMATIC,),
                status=SampleStatus.DECODED,
                image=make_artifact(),
            ),
            SampleResult(
                sample_id=other_shot_sample,
                shot_id=other_shot_id,
                requested_ms=500,
                decoded_ms=500,
                purposes=(SamplePurpose.CHROMATIC,),
                status=SampleStatus.DECODED,
                image=make_artifact(),
            ),
        ),
    )
    frames = collect_shot_frames(manifest, {SAMPLE_ID: blob.storage_key}, store, SHOT_ID)
    assert len(frames) == 1
    assert frames[0].jpeg == jpeg


def test_video_summary_uses_float_median_for_even_counts() -> None:
    shot_set = make_shot_set(
        shots=(
            make_shot(index=0, start_ms=0, end_ms=1000),
            make_shot(index=1, start_ms=1000, end_ms=4000),
        )
    )
    summary = video_summary(shot_set, 4000)
    assert summary.shot_count == 2
    assert summary.average_shot_length_ms == 2000.0
    assert summary.median_shot_length_ms == 2000.0
    assert summary.shots_per_minute == 30.0


def test_video_summary_uses_the_middle_shot_for_odd_counts() -> None:
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=4000),))
    summary = video_summary(shot_set, 4000)
    assert summary.shot_count == 1
    assert summary.median_shot_length_ms == 4000.0
    assert summary.shots_per_minute == 15.0


def test_chromatic_availability_complete_partial_and_unavailable() -> None:
    ok = make_ok_chromatic()
    missing = ChromaticMeasurement(
        status=MetricStatus.INSUFFICIENT_DATA,
        value=None,
        reason_code="chromatic_letterbox_insufficient",
        method=make_provenance(),
    )
    assert chromatic_availability((ok, ok)) is StageAvailability.COMPLETE
    assert chromatic_availability((ok, missing)) is StageAvailability.PARTIAL
    assert chromatic_availability((missing,)) is StageAvailability.UNAVAILABLE
    assert chromatic_availability(()) is StageAvailability.UNAVAILABLE


def test_assemble_report_marks_spatial_unavailable_without_a_detector() -> None:
    video = video_record_from_bytes(b"clip")
    analysis = (
        CreateAnalysis(FakeRepository())
        .execute(video=video, config=tiny_config(), request_id="req-phase-03")
        .analysis
    )
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=4000),))
    stamp = datetime(2026, 9, 6, tzinfo=UTC)
    report = assemble_report(
        video=video,
        analysis=analysis,
        config=tiny_config(),
        shot_set=shot_set,
        chromatic=(make_ok_chromatic(),),
        spatial=(make_unavailable_spatial(),),
        generated_at=stamp,
        started_at=stamp,
        completed_at=stamp,
    )
    assert report.availability.spatial is StageAvailability.UNAVAILABLE
    assert report.shots[0].spatial.status is MetricStatus.NOT_COMPUTED
    assert report.shots[0].spatial.reason_code == "detector_not_installed"
    assert report.shots[0].temporal.value is not None
    assert report.shots[0].temporal.value.duration_ms == 4000
    assert report.availability.chromatic is StageAvailability.COMPLETE


def test_assemble_report_rejects_a_shot_count_mismatch() -> None:
    video = video_record_from_bytes(b"clip")
    analysis = (
        CreateAnalysis(FakeRepository())
        .execute(video=video, config=tiny_config(), request_id="req-phase-03")
        .analysis
    )
    stamp = datetime(2026, 9, 6, tzinfo=UTC)
    with pytest.raises(ValueError, match="match shot count"):
        assemble_report(
            video=video,
            analysis=analysis,
            config=tiny_config(),
            shot_set=make_shot_set(),
            chromatic=(make_ok_chromatic(), make_ok_chromatic()),
            spatial=(make_unavailable_spatial(),),
            generated_at=stamp,
            started_at=stamp,
            completed_at=stamp,
        )


class _Detector:
    def detect(self, path: object, config: object, *, duration_ms: int) -> DetectionResult:
        assert duration_ms > 0
        assert config is not None
        assert path is not None
        return DetectionResult(boundaries=(), debug_stats=None)


class _Extractor:
    def __init__(self, jpeg: bytes) -> None:
        self.jpeg = jpeg

    def extract(
        self,
        path: object,
        requests: tuple[object, ...],
        ranges: object,
        *,
        rotation_degrees: int,
    ) -> tuple[DecodedSample, ...]:
        assert path is not None
        assert ranges is not None
        assert rotation_degrees == 0
        return tuple(
            DecodedSample(
                sample_id=request.sample_id,  # type: ignore[attr-defined]
                requested_ms=request.requested_ms,  # type: ignore[attr-defined]
                decoded_ms=request.requested_ms,  # type: ignore[attr-defined]
                frame_index=0,
                jpeg=self.jpeg,
                unavailable_reason=None,
            )
            for request in requests
        )


class _Analyzer:
    def __init__(self, computed: ChromaticComputeResult) -> None:
        self.computed = computed
        self.calls = 0

    def analyze_shot(
        self,
        frames: tuple[ChromaticFrame, ...],
        config: object,
    ) -> ChromaticComputeResult:
        self.calls += 1
        assert frames
        assert config is not None
        return self.computed


def test_report_stage_persists_chromatics_and_report(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    analysis = (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id="req-phase-03")
        .analysis
    )
    computed = ChromaticComputeResult(
        status=MetricStatus.OK,
        value=make_ok_chromatic().value,
        confidence=0.6,
        reason_code=None,
        evidence_sample_ids=(SAMPLE_ID,),
    )
    analyzer = _Analyzer(computed)
    sampling = RunSamplingStages(store, _Detector(), _Extractor(b"\xff\xd8xx"), repo)
    result = make_run_report_stages(sampling, store, analyzer, fake_analyzer(), repo).execute(
        video=video,
        analysis=analysis,
        config=tiny_config(),
        request_id="req-phase-03",
    )
    assert analyzer.calls >= 1
    assert result.report.availability.chromatic is StageAvailability.COMPLETE
    assert store.contains(result.report_key)
    assert store.contains(result.chromatics_key)
    assert store.contains(result.spatial_key)
    assert store.contains(result.timeline_key)
    assert result.report.availability.spatial is StageAvailability.UNAVAILABLE
    assert result.report.shots[0].spatial.reason_code == "detector_not_installed"


def test_report_stage_wraps_sampling_adapter_errors(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    analysis = (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id="req-phase-03")
        .analysis
    )

    class _Boom:
        def detect(self, path: object, config: object, *, duration_ms: int) -> DetectionResult:
            assert path is not None
            assert config is not None
            assert duration_ms > 0
            raise AdapterError("SHOT_FAILED", "detector failed", retryable=True, stage="shots")

    dummy = ChromaticComputeResult(
        status=MetricStatus.FAILED,
        value=None,
        confidence=None,
        reason_code="unused",
        evidence_sample_ids=(),
    )
    sampling = RunSamplingStages(store, _Boom(), _Extractor(b"x"), repo)
    with pytest.raises(IngestError) as caught:
        make_run_report_stages(sampling, store, _Analyzer(dummy), fake_analyzer(), repo).execute(
            video=video,
            analysis=analysis,
            config=tiny_config(),
            request_id="req-phase-03",
        )
    assert caught.value.safe.code == "SHOT_FAILED"
    assert caught.value.safe.stage == "shots"


def test_report_stage_records_insufficient_when_no_chromatic_frames(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    analysis = (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id="req-phase-03")
        .analysis
    )

    class _Blank:
        def extract(
            self,
            path: object,
            requests: tuple[object, ...],
            ranges: object,
            *,
            rotation_degrees: int,
        ) -> tuple[DecodedSample, ...]:
            assert path is not None
            assert ranges is not None
            assert rotation_degrees == 0
            return tuple(
                DecodedSample(
                    sample_id=request.sample_id,  # type: ignore[attr-defined]
                    requested_ms=request.requested_ms,  # type: ignore[attr-defined]
                    decoded_ms=None,
                    frame_index=None,
                    jpeg=None,
                    unavailable_reason="missing",
                )
                for request in requests
            )

    dummy = ChromaticComputeResult(
        status=MetricStatus.OK,
        value=make_ok_chromatic().value,
        confidence=1.0,
        reason_code=None,
        evidence_sample_ids=(),
    )
    analyzer = _Analyzer(dummy)
    sampling = RunSamplingStages(store, _Detector(), _Blank(), repo)
    result = make_run_report_stages(sampling, store, analyzer, fake_analyzer(), repo).execute(
        video=video,
        analysis=analysis,
        config=tiny_config(),
        request_id="req-phase-03",
    )
    assert analyzer.calls == 0
    assert result.report.availability.chromatic is StageAvailability.UNAVAILABLE
    assert result.report.shots[0].chromatic.reason_code == "chromatic_no_decoded_samples"


def test_report_stage_wraps_chromatic_adapter_errors(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    analysis = (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id="req-phase-03")
        .analysis
    )

    class _Raise:
        def analyze_shot(
            self,
            frames: tuple[ChromaticFrame, ...],
            config: object,
        ) -> ChromaticComputeResult:
            assert frames
            assert config is not None
            raise AdapterError(
                "ARTIFACT_WRITE",
                "chromatic artifact write failed",
                retryable=True,
                stage="chromatic",
            )

    sampling = RunSamplingStages(store, _Detector(), _Extractor(b"\xff\xd8xx"), repo)
    with pytest.raises(IngestError) as caught:
        make_run_report_stages(sampling, store, _Raise(), fake_analyzer(), repo).execute(
            video=video,
            analysis=analysis,
            config=tiny_config(),
            request_id="req-phase-03",
        )
    assert caught.value.safe.code == "ARTIFACT_WRITE"
    assert caught.value.safe.stage == "chromatic"
