"""PostgreSQL adapter maps engine failures without leaking internals."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from tests.factories import DIGEST, make_artifact, make_availability, make_video

from cine_analyzer.adapters.persistence.postgres import PostgresJobRepository, _updated_one
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import Critique, VideoSummary
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.control import CritiqueRunRecord, ReportSummaryRecord, StageLease
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord


class _Boom:
    def __enter__(self) -> "_Boom":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def begin(self) -> "_Boom":
        raise SQLAlchemyError("boom")

    def get(self, *_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError("boom")

    def scalar(self, *_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError("boom")

    def scalars(self, *_args: object, **_kwargs: object) -> "_Boom":
        return self

    def all(self) -> list[object]:
        raise SQLAlchemyError("boom")

    def execute(self, *_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError("boom")

    def add(self, *_args: object, **_kwargs: object) -> None:
        raise SQLAlchemyError("boom")

    def flush(self) -> None:
        raise SQLAlchemyError("boom")


def _repo() -> PostgresJobRepository:
    return PostgresJobRepository("postgresql+pg8000://cine:@127.0.0.1:1/missing")


def test_ping_unreachable_host_is_resource_state() -> None:
    repo = _repo()
    try:
        with pytest.raises(AdapterError) as caught:
            repo.ping()
        assert caught.value.code == "RESOURCE_STATE"
        assert caught.value.retryable is True
    finally:
        repo.close()


def test_session_failures_map_to_resource_state() -> None:
    repo = _repo()
    repo._sessions = _Boom  # type: ignore[method-assign]
    now = datetime.now(tz=UTC)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    analysis = AnalysisRecord(
        analysis_id=uuid4(),
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="a" * 64,
        state=AnalysisState.QUEUED,
    )
    lease = StageLease(
        stage_run_id=uuid4(),
        analysis_id=analysis.analysis_id,
        stage_name="sampling",
        attempt=1,
        token=uuid4(),
        worker_id="w",
        expires_at=now,
    )
    calls = [
        lambda: repo.get_video_by_hash(DIGEST),
        lambda: repo.get_video(video.metadata.video_id),
        lambda: repo.insert_video(video),
        lambda: repo.get_analysis_by_key("a" * 64),
        lambda: repo.get_analysis(analysis.analysis_id),
        lambda: repo.insert_analysis(analysis),
        lambda: repo.insert_artifact(make_artifact(), storage_key="k"),
        lambda: repo.load_job(analysis.analysis_id),
        lambda: repo.record_config(analysis.analysis_id, AnalysisConfig()),
        lambda: repo.ensure_pending_stages(analysis.analysis_id),
        lambda: repo.list_stage_runs(analysis.analysis_id),
        lambda: repo.claim_queued(worker_id="w", now=now),
        lambda: repo.request_cancel(analysis.analysis_id, now=now),
        lambda: repo.set_analysis_state(
            analysis.analysis_id,
            expected=AnalysisState.QUEUED,
            target=AnalysisState.RUNNING,
        ),
        lambda: repo.acquire_stage(
            analysis.analysis_id, "sampling", worker_id="w", ttl_ms=1000, now=now
        ),
        lambda: repo.start_stage(lease, now=now),
        lambda: repo.heartbeat_stage(lease, ttl_ms=1000, now=now),
        lambda: repo.complete_stage(lease, now=now),
        lambda: repo.fail_stage(lease, terminal=True, code="RESOURCE_STATE", message="x", now=now),
        lambda: repo.cancel_stage(analysis.analysis_id, "sampling", 1),
        lambda: repo.insert_retry_attempt(analysis.analysis_id, "sampling"),
        lambda: repo.get_artifact(uuid4()),
        lambda: repo.get_artifact_by_storage_key("k"),
        lambda: repo.save_shots(analysis.analysis_id, ()),
        lambda: repo.get_shot(analysis.analysis_id, uuid4()),
        lambda: repo.save_report_summary(
            ReportSummaryRecord(
                analysis_id=analysis.analysis_id,
                summary=VideoSummary(
                    shot_count=1,
                    average_shot_length_ms=1.0,
                    median_shot_length_ms=1.0,
                    shots_per_minute=1.0,
                ),
                availability=make_availability(),
                report_artifact_id=uuid4(),
                timeline_artifact_id=None,
            )
        ),
        lambda: repo.get_report_summary(analysis.analysis_id),
        lambda: repo.save_critique(
            CritiqueRunRecord(
                critique_run_id=uuid4(),
                analysis_id=analysis.analysis_id,
                critique=Critique(status=MetricStatus.NOT_COMPUTED),
                created_at=now,
            )
        ),
        lambda: repo.get_latest_critique(analysis.analysis_id),
        lambda: repo.get_critique_by_identity(
            analysis.analysis_id,
            prompt_version="critic-prompt-v1",
            model_name="fake:deterministic-v1",
            input_report_sha256="a" * 64,
        ),
        lambda: repo.link_artifact(uuid4(), analysis_id=analysis.analysis_id),
        repo.count_inflight,
    ]
    try:
        for call in calls:
            with pytest.raises(AdapterError) as caught:
                call()
            assert caught.value.code == "RESOURCE_STATE"
        with pytest.raises(AdapterError) as empty:
            repo.claim_queued(worker_id="", now=now)
        assert empty.value.retryable is False
        assert (
            repo.set_analysis_state(
                analysis.analysis_id,
                expected=AnalysisState.SUCCEEDED,
                target=AnalysisState.QUEUED,
            )
            is False
        )
    finally:
        repo.close()


def test_updated_one_treats_missing_rowcount_as_zero() -> None:
    class _NoCount:
        pass

    assert _updated_one(_NoCount()) is False  # type: ignore[arg-type]
