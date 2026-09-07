"""Aggregator rules: required failure, optional partial, no-audio success."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from tests.factories import (
    ANALYSIS_ID,
    DIGEST,
    SHOT_ID,
    VIDEO_ID,
    make_artifact,
    make_availability,
    make_report,
    make_video,
)
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.aggregation import (
    decide_analysis_outcome,
    persist_report_outcome,
    progress_from_stages,
    unavailable_pillars,
)
from cine_analyzer.domain.jobs import AnalysisState, StageState
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.ports.control import StageRunRecord
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord


def _run(
    name: str,
    state: StageState,
    *,
    attempt: int = 1,
    analysis_id: UUID = ANALYSIS_ID,
) -> StageRunRecord:
    return StageRunRecord(
        stage_run_id=uuid4(),
        analysis_id=analysis_id,
        stage_name=name,
        attempt=attempt,
        state=state,
        lease_token=None,
        worker_id=None,
        lease_expires_at=None,
        error_code=None,
        error_message=None,
    )


def test_required_stage_failure_fails_the_analysis() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.FAILED_TERMINAL),
    )
    outcome = decide_analysis_outcome(
        runs,
        make_availability(),
        has_audio=False,
        spatial_requested=False,
    )
    assert outcome is AnalysisState.FAILED


def test_missing_required_stage_fails_the_analysis() -> None:
    outcome = decide_analysis_outcome(
        (_run("sampling", StageState.SUCCEEDED),),
        make_availability(),
        has_audio=False,
        spatial_requested=False,
    )
    assert outcome is AnalysisState.FAILED


def test_no_availability_after_required_success_fails() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    assert (
        decide_analysis_outcome(runs, None, has_audio=False, spatial_requested=False)
        is AnalysisState.FAILED
    )


def test_motion_unavailable_is_partial() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.UNAVAILABLE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.PARTIAL
    )
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.PARTIAL,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.PARTIAL
    )


def test_spatial_unavailable_with_backend_none_is_not_a_failure() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.SUCCEEDED
    )


def test_spatial_unavailable_when_requested_is_partial() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=True)
        is AnalysisState.PARTIAL
    )


def test_no_audio_source_with_unavailable_audio_can_succeed() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.SUCCEEDED
    )


def test_audio_extract_failure_when_source_has_audio_is_partial() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=True, spatial_requested=False)
        is AnalysisState.PARTIAL
    )


def test_tension_unavailable_is_partial() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.UNAVAILABLE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.PARTIAL
    )


def test_chromatic_unavailable_is_partial() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.UNAVAILABLE,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.PARTIAL
    )


def test_latest_attempt_wins_for_required_stages() -> None:
    runs = (
        _run("sampling", StageState.FAILED_RETRYABLE, attempt=1),
        _run("sampling", StageState.SUCCEEDED, attempt=2),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        motion=StageAvailability.COMPLETE,
        tension=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.SUCCEEDED
    )


def test_progress_sums_weights_for_succeeded_and_skipped() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SKIPPED),
        _run("aggregate", StageState.PENDING),
    )
    assert progress_from_stages(runs) == 0.9


def test_progress_is_zero_when_nothing_finished() -> None:
    assert progress_from_stages(()) == 0.0


def test_unavailable_pillars_lists_non_complete_names() -> None:
    names = unavailable_pillars(make_availability())
    assert "spatial" in names
    assert "critic" in names
    assert "shots" not in names


def test_persist_report_outcome_writes_summary_and_succeeded_state(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    video = VideoRecord(
        metadata=make_video(has_audio=False),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    record = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="c" * 64,
        state=AnalysisState.QUEUED,
    )
    jobs.insert_analysis(record)
    assert jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    jobs.ensure_pending_stages(ANALYSIS_ID)
    now = datetime.now(tz=UTC)
    for name in ("sampling", "report"):
        lease = jobs.acquire_stage(ANALYSIS_ID, name, worker_id="w", ttl_ms=1000, now=now)
        assert lease is not None
        assert jobs.start_stage(lease, now=now)
        assert jobs.complete_stage(lease, now=now)
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        motion=StageAvailability.COMPLETE,
        tension=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
    )
    report = make_report(availability=availability)
    key = f"analyses/{ANALYSIS_ID.hex}/report.json"
    blob = store.put_bytes(report.model_dump_json().encode("utf-8"), storage_key=key)
    jobs.insert_artifact(make_artifact(kind="analysis_report"), storage_key=key)
    _ = blob
    outcome = persist_report_outcome(jobs, store, ANALYSIS_ID)
    assert outcome is AnalysisState.SUCCEEDED
    assert jobs.get_report_summary(ANALYSIS_ID) is not None
    assert jobs.get_shot(ANALYSIS_ID, SHOT_ID) is not None


def test_persist_fails_when_the_report_artifact_is_missing(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="d" * 64,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    assert persist_report_outcome(jobs, store, ANALYSIS_ID) is AnalysisState.FAILED
    job = jobs.load_job(ANALYSIS_ID)
    assert job is not None
    assert job.record.state is AnalysisState.FAILED


def test_persist_fails_when_the_job_row_is_gone(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    assert persist_report_outcome(jobs, store, ANALYSIS_ID) is AnalysisState.FAILED


def test_persist_fails_on_invalid_report_bytes(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="e" * 64,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    key = f"analyses/{ANALYSIS_ID.hex}/report.json"
    store.put_bytes(b"not-json", storage_key=key)
    jobs.insert_artifact(make_artifact(kind="analysis_report"), storage_key=key)
    assert persist_report_outcome(jobs, store, ANALYSIS_ID) is AnalysisState.FAILED


def test_persist_fails_when_the_video_row_is_missing(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="f" * 64,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    assert persist_report_outcome(jobs, store, ANALYSIS_ID) is AnalysisState.FAILED


def test_persist_links_timeline_and_uses_oserror_path(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    video = VideoRecord(
        metadata=make_video(has_audio=False),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="11" + "c" * 62,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    now = datetime.now(tz=UTC)
    jobs.ensure_pending_stages(ANALYSIS_ID)
    for name in ("sampling", "report"):
        lease = jobs.acquire_stage(ANALYSIS_ID, name, worker_id="w", ttl_ms=1000, now=now)
        assert lease is not None
        assert jobs.start_stage(lease, now=now)
        assert jobs.complete_stage(lease, now=now)
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        motion=StageAvailability.COMPLETE,
        tension=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
    )
    report = make_report(availability=availability)
    report_key = f"analyses/{ANALYSIS_ID.hex}/report.json"
    timeline_key = f"analyses/{ANALYSIS_ID.hex}/timeline.json"
    store.put_bytes(report.model_dump_json().encode("utf-8"), storage_key=report_key)
    store.put_bytes(b"{}", storage_key=timeline_key)
    jobs.insert_artifact(
        make_artifact(artifact_id=uuid4(), kind="analysis_report"), storage_key=report_key
    )
    jobs.insert_artifact(
        make_artifact(artifact_id=uuid4(), kind="timeline"), storage_key=timeline_key
    )
    assert persist_report_outcome(jobs, store, ANALYSIS_ID) is AnalysisState.SUCCEEDED

    class _Missing:
        def local_path(self, storage_key: str) -> Path:
            del storage_key
            return Path("/definitely/missing/report.json")

    jobs2 = MemoryJobRepository()
    jobs2.insert_video(video)
    jobs2.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="22" + "c" * 62,
            state=AnalysisState.QUEUED,
        )
    )
    jobs2.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    jobs2.insert_artifact(make_artifact(kind="analysis_report"), storage_key=report_key)
    assert persist_report_outcome(jobs2, _Missing(), ANALYSIS_ID) is AnalysisState.FAILED  # type: ignore[arg-type]


def test_decide_pending_required_stage_is_failed() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.PENDING),
        _run("sampling", StageState.FAILED_RETRYABLE, attempt=0),
    )
    assert (
        decide_analysis_outcome(runs, make_availability(), has_audio=False, spatial_requested=False)
        is AnalysisState.FAILED
    )
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    availability = make_availability(
        chromatic=StageAvailability.PARTIAL,
        spatial=StageAvailability.UNAVAILABLE,
        motion=StageAvailability.COMPLETE,
        audio=StageAvailability.UNAVAILABLE,
        tension=StageAvailability.COMPLETE,
    )
    assert (
        decide_analysis_outcome(runs, availability, has_audio=False, spatial_requested=False)
        is AnalysisState.PARTIAL
    )
