"""Shared lease/run/complete path used by local and Celery workers."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_video
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.errors import IngestError, ingest_error
from cine_analyzer.application.stage_execute import (
    StageOutcome,
    honor_cancel,
    run_leased_stage,
    should_cancel,
    tick_cancel,
)
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord


def _seed(jobs: MemoryJobRepository) -> AnalysisRecord:
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    analysis = jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(uuid4().bytes).hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    jobs.record_config(analysis.analysis_id, AnalysisConfig())
    jobs.ensure_pending_stages(analysis.analysis_id)
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    return analysis


def test_tick_cancel_none_is_a_no_op() -> None:
    tick_cancel(None)


def test_skip_succeeded_and_cancel(tmp_path: Path) -> None:
    del tmp_path
    jobs = MemoryJobRepository()
    analysis = _seed(jobs)
    now = datetime.now(tz=UTC)
    lease = jobs.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="w", ttl_ms=1000, now=now
    )
    assert lease is not None
    assert jobs.start_stage(lease, now=now)
    assert jobs.complete_stage(lease, now=now)
    outcome = run_leased_stage(
        jobs,
        analysis.analysis_id,
        "sampling",
        worker_id="w",
        ttl_ms=1000,
        now=now,
        work=lambda: None,
    )
    assert outcome is StageOutcome.SKIPPED

    jobs.set_analysis_state(
        analysis.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.CANCEL_REQUESTED,
    )
    assert should_cancel(jobs, analysis.analysis_id)
    canceled = run_leased_stage(
        jobs,
        analysis.analysis_id,
        "report",
        worker_id="w",
        ttl_ms=1000,
        now=now,
        work=lambda: None,
    )
    assert canceled is StageOutcome.CANCELED


def test_lease_start_complete_failures(tmp_path: Path) -> None:
    del tmp_path
    jobs = MemoryJobRepository()
    analysis = _seed(jobs)
    now = datetime.now(tz=UTC)
    jobs.acquire_stage = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    lost = run_leased_stage(
        jobs,
        analysis.analysis_id,
        "sampling",
        worker_id="w",
        ttl_ms=1000,
        now=now,
        work=lambda: None,
    )
    assert lost is StageOutcome.LEASE_LOST

    jobs2 = MemoryJobRepository()
    analysis2 = _seed(jobs2)
    jobs2.start_stage = lambda *_args, **_kwargs: False  # type: ignore[method-assign]
    assert (
        run_leased_stage(
            jobs2,
            analysis2.analysis_id,
            "sampling",
            worker_id="w",
            ttl_ms=1000,
            now=now,
            work=lambda: None,
        )
        is StageOutcome.LEASE_LOST
    )

    jobs3 = MemoryJobRepository()
    analysis3 = _seed(jobs3)
    jobs3.complete_stage = lambda *_args, **_kwargs: False  # type: ignore[method-assign]
    assert (
        run_leased_stage(
            jobs3,
            analysis3.analysis_id,
            "sampling",
            worker_id="w",
            ttl_ms=1000,
            now=now,
            work=lambda: None,
        )
        is StageOutcome.LEASE_LOST
    )


def test_canceled_error_and_retry_cap(tmp_path: Path) -> None:
    del tmp_path
    jobs = MemoryJobRepository()
    analysis = _seed(jobs)
    now = datetime.now(tz=UTC)

    def boom_cancel() -> None:
        raise ingest_error(
            "CANCELED_BY_CLIENT",
            "canceled",
            request_id="r",
            retryable=False,
            stage="sampling",
        )

    outcome = run_leased_stage(
        jobs,
        analysis.analysis_id,
        "sampling",
        worker_id="w",
        ttl_ms=1000,
        now=now,
        work=boom_cancel,
    )
    assert outcome is StageOutcome.CANCELED

    jobs4 = MemoryJobRepository()
    analysis4 = _seed(jobs4)

    def boom() -> None:
        raise ingest_error("RESOURCE_STATE", "temp", request_id="r", retryable=True)

    with pytest.raises(IngestError, match="temp"):
        run_leased_stage(
            jobs4,
            analysis4.analysis_id,
            "sampling",
            worker_id="w",
            ttl_ms=1000,
            now=now,
            work=boom,
            max_attempts=1,
        )
    loaded = jobs4.load_job(analysis4.analysis_id)
    assert loaded is not None
    assert loaded.record.state is AnalysisState.FAILED
    honor_cancel(jobs4, analysis4.analysis_id)
    store = MemoryStore(Path())
    del store
