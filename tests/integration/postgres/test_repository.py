"""PostgreSQL repository: uniqueness, leases, stale complete, retry."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_artifact, make_availability, make_video

from cine_analyzer.adapters.persistence.postgres import PostgresJobRepository
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import Critique, VideoSummary
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.control import (
    CritiqueRunRecord,
    ReportSummaryRecord,
    ShotIntervalRecord,
    StageLease,
)
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord


def _video(digest: str | None = None) -> VideoRecord:
    payload = DIGEST if digest is None else digest
    return VideoRecord(
        metadata=make_video(video_id=uuid4(), content_sha256=payload),
        original_storage_key="aa/" + payload[:64],
        probe_storage_key="bb/" + payload[:64],
    )


def test_duplicate_video_and_analysis_reuse(pg_repo: PostgresJobRepository) -> None:
    first = pg_repo.insert_video(_video())
    second = pg_repo.insert_video(_video())
    assert second.metadata.video_id == first.metadata.video_id
    key = sha256(b"pg-analysis").hexdigest()
    record = AnalysisRecord(
        analysis_id=uuid4(),
        video_id=first.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key=key,
        state=AnalysisState.QUEUED,
    )
    created = pg_repo.insert_analysis(record)
    reused = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=first.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=key,
            state=AnalysisState.QUEUED,
        )
    )
    assert reused.analysis_id == created.analysis_id
    assert pg_repo.get_video(first.metadata.video_id) is not None
    assert pg_repo.get_analysis(created.analysis_id) is not None
    pg_repo.record_config(created.analysis_id, AnalysisConfig())
    pg_repo.ensure_pending_stages(created.analysis_id)
    pg_repo.ensure_pending_stages(created.analysis_id)
    assert pg_repo.load_job(created.analysis_id) is not None


def test_conflicting_video_primary_key_is_rejected(pg_repo: PostgresJobRepository) -> None:
    first = pg_repo.insert_video(_video())
    other_hash = sha256(b"other-pg").hexdigest()
    colliding = VideoRecord(
        metadata=make_video(video_id=first.metadata.video_id, content_sha256=other_hash),
        original_storage_key="cc/" + "c" * 64,
        probe_storage_key="dd/" + "d" * 64,
    )
    with pytest.raises(AdapterError):
        pg_repo.insert_video(colliding)


def test_two_claimants_and_stale_complete(pg_repo: PostgresJobRepository) -> None:
    video = pg_repo.insert_video(_video(sha256(b"lease").hexdigest()))
    analysis = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"lease-key").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    pg_repo.ensure_pending_stages(analysis.analysis_id)
    now = datetime.now(tz=UTC)
    first = pg_repo.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="a", ttl_ms=5_000, now=now
    )
    second = pg_repo.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="b", ttl_ms=5_000, now=now
    )
    assert first is not None
    assert second is None
    expired = now - timedelta(seconds=30)
    stale = pg_repo.acquire_stage(
        analysis.analysis_id, "report", worker_id="old", ttl_ms=1, now=expired
    )
    assert stale is not None
    assert pg_repo.start_stage(stale, now=expired)
    fresh = pg_repo.acquire_stage(
        analysis.analysis_id, "report", worker_id="new", ttl_ms=5_000, now=now
    )
    assert fresh is not None
    assert pg_repo.start_stage(fresh, now=now)
    assert pg_repo.complete_stage(stale, now=now) is False
    assert pg_repo.complete_stage(fresh, now=now) is True
    assert pg_repo.start_stage(first, now=now)
    assert pg_repo.heartbeat_stage(first, ttl_ms=5_000, now=now)
    assert pg_repo.fail_stage(first, terminal=False, code="RESOURCE_STATE", message="busy", now=now)
    retry = pg_repo.insert_retry_attempt(analysis.analysis_id, "sampling")
    assert retry.attempt == 2
    claimed = pg_repo.claim_queued(worker_id="w", now=now)
    assert claimed is not None
    canceled = pg_repo.request_cancel(analysis.analysis_id, now=now)
    assert canceled is not None
    assert pg_repo.request_cancel(uuid4(), now=now) is None


def test_shots_summaries_artifacts_and_ping(pg_repo: PostgresJobRepository) -> None:
    video = pg_repo.insert_video(_video(sha256(b"shots").hexdigest()))
    analysis = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"shots-key").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    pg_repo.ping()
    ref = make_artifact()
    pg_repo.insert_artifact(ref, storage_key="ee/" + "e" * 64)
    pg_repo.insert_artifact(ref, storage_key="ee/" + "e" * 64)
    assert pg_repo.get_artifact(ref.artifact_id) is not None
    assert pg_repo.get_artifact_by_storage_key("ee/" + "e" * 64) is not None
    pg_repo.link_artifact(ref.artifact_id, analysis_id=analysis.analysis_id)
    shot_id = uuid4()
    pg_repo.save_shots(
        analysis.analysis_id,
        (
            ShotIntervalRecord(
                shot_id=shot_id,
                analysis_id=analysis.analysis_id,
                shot_index=0,
                start_ms=0,
                end_ms=1000,
            ),
        ),
    )
    assert pg_repo.get_shot(analysis.analysis_id, shot_id) is not None
    assert pg_repo.get_shot(analysis.analysis_id, uuid4()) is None
    pg_repo.save_report_summary(
        ReportSummaryRecord(
            analysis_id=analysis.analysis_id,
            summary=VideoSummary(
                shot_count=1,
                average_shot_length_ms=1000.0,
                median_shot_length_ms=1000.0,
                shots_per_minute=60.0,
            ),
            availability=make_availability(),
            report_artifact_id=ref.artifact_id,
            timeline_artifact_id=None,
        )
    )
    pg_repo.save_report_summary(
        ReportSummaryRecord(
            analysis_id=analysis.analysis_id,
            summary=VideoSummary(
                shot_count=1,
                average_shot_length_ms=1000.0,
                median_shot_length_ms=1000.0,
                shots_per_minute=60.0,
            ),
            availability=make_availability(),
            report_artifact_id=ref.artifact_id,
            timeline_artifact_id=None,
        )
    )
    assert pg_repo.get_report_summary(analysis.analysis_id) is not None
    pg_repo.save_critique(
        CritiqueRunRecord(
            critique_run_id=uuid4(),
            analysis_id=analysis.analysis_id,
            critique=Critique(
                status=MetricStatus.OK,
                text="The clip has 1 detected shots with mean length 1.0 s and median 1.0 s.",
                model_name="fake:deterministic-v1",
                prompt_version="critic-prompt-v1",
                input_report_sha256=DIGEST,
            ),
            created_at=datetime.now(tz=UTC),
        )
    )
    assert pg_repo.get_latest_critique(analysis.analysis_id) is not None
    assert (
        pg_repo.get_critique_by_identity(
            analysis.analysis_id,
            prompt_version="critic-prompt-v1",
            model_name="fake:deterministic-v1",
            input_report_sha256=DIGEST,
        )
        is not None
    )
    assert (
        pg_repo.get_critique_by_identity(
            analysis.analysis_id,
            prompt_version="other",
            model_name="fake:deterministic-v1",
            input_report_sha256=DIGEST,
        )
        is None
    )
    pg_repo.cancel_stage(analysis.analysis_id, "sampling", 1)
    pg_repo.set_analysis_state(
        analysis.analysis_id,
        expected=AnalysisState.QUEUED,
        target=AnalysisState.RUNNING,
    )
    pg_repo.set_analysis_state(
        analysis.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.FAILED,
        failure_code="RESOURCE_STATE",
        failure_message="stopped",
        progress=0.4,
    )
    with pytest.raises(AdapterError):
        pg_repo.claim_queued(worker_id="", now=datetime.now(tz=UTC))


def test_claim_cancel_and_missing_lookups(pg_repo: PostgresJobRepository) -> None:
    assert pg_repo.claim_queued(worker_id="w", now=datetime.now(tz=UTC)) is None
    assert pg_repo.get_video_by_hash("0" * 64) is None
    assert pg_repo.get_analysis_by_key("0" * 64) is None
    assert pg_repo.get_analysis(uuid4()) is None
    assert pg_repo.load_job(uuid4()) is None
    assert pg_repo.get_artifact(uuid4()) is None
    assert pg_repo.get_artifact_by_storage_key("missing") is None
    assert pg_repo.get_report_summary(uuid4()) is None
    assert pg_repo.get_latest_critique(uuid4()) is None
    video = pg_repo.insert_video(_video(sha256(b"claim-empty").hexdigest()))
    analysis = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"claim-empty-key").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    pg_repo.ensure_pending_stages(analysis.analysis_id, ())
    assert pg_repo.count_inflight() >= 1
    canceled = pg_repo.request_cancel(analysis.analysis_id, now=datetime.now(tz=UTC))
    assert canceled is not None
    assert canceled.state is AnalysisState.CANCELED
    other_video = pg_repo.insert_video(_video(sha256(b"running-reclaim-video").hexdigest()))
    other = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=other_video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"running-reclaim").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    pg_repo.ensure_pending_stages(other.analysis_id)
    now = datetime.now(tz=UTC)
    assert pg_repo.set_analysis_state(
        other.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    reclaimed = pg_repo.claim_queued(worker_id="w", now=now)
    assert reclaimed is not None
    assert reclaimed.analysis_id == other.analysis_id
    assert (
        pg_repo.set_analysis_state(
            other.analysis_id,
            expected=AnalysisState.QUEUED,
            target=AnalysisState.RUNNING,
        )
        is False
    )
    assert (
        pg_repo.acquire_stage(other.analysis_id, "missing", worker_id="w", ttl_ms=1000, now=now)
        is None
    )
    assert pg_repo.cancel_stage(other.analysis_id, "sampling", 99) is False
    fake = StageLease(
        stage_run_id=uuid4(),
        analysis_id=other.analysis_id,
        stage_name="sampling",
        attempt=1,
        token=uuid4(),
        worker_id="w",
        expires_at=now,
    )
    assert pg_repo.heartbeat_stage(fake, ttl_ms=1000, now=now) is False
    colliding = AnalysisRecord(
        analysis_id=other.analysis_id,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key=sha256(b"pk-collision").hexdigest(),
        state=AnalysisState.QUEUED,
    )
    with pytest.raises(AdapterError):
        pg_repo.insert_analysis(colliding)


def test_cancel_requested_reclaim_and_retry_without_prior_rows(
    pg_repo: PostgresJobRepository,
) -> None:
    video = pg_repo.insert_video(_video(sha256(b"cancel-reclaim").hexdigest()))
    analysis = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"cancel-reclaim-key").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    pg_repo.ensure_pending_stages(analysis.analysis_id)
    now = datetime.now(tz=UTC)
    assert pg_repo.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    canceled = pg_repo.request_cancel(analysis.analysis_id, now=now)
    assert canceled is not None
    assert canceled.state is AnalysisState.CANCEL_REQUESTED
    reclaimed = pg_repo.claim_queued(worker_id="w", now=now)
    assert reclaimed is not None
    assert reclaimed.analysis_id == analysis.analysis_id
    assert reclaimed.state is AnalysisState.CANCEL_REQUESTED
    orphan_video = pg_repo.insert_video(_video(sha256(b"retry-orphan-video").hexdigest()))
    orphan = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=orphan_video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"retry-orphan").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    retry = pg_repo.insert_retry_attempt(orphan.analysis_id, "sampling")
    assert retry.attempt == 1
    finished_video = pg_repo.insert_video(_video(sha256(b"already-done-video").hexdigest()))
    finished = pg_repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=finished_video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"already-done").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    assert pg_repo.set_analysis_state(
        finished.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    report_ref = make_artifact(artifact_id=uuid4(), kind="analysis_report")
    timeline_ref = make_artifact(artifact_id=uuid4(), kind="timeline")
    pg_repo.insert_artifact(report_ref, storage_key="rr/" + "r" * 64)
    pg_repo.insert_artifact(timeline_ref, storage_key="tt/" + "t" * 64)
    assert pg_repo.set_analysis_state(
        finished.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.SUCCEEDED,
        progress=1.0,
        report_artifact_id=report_ref.artifact_id,
        timeline_artifact_id=timeline_ref.artifact_id,
    )
    still = pg_repo.request_cancel(finished.analysis_id, now=now)
    assert still is not None
    assert still.state is AnalysisState.SUCCEEDED
    lease = pg_repo.acquire_stage(
        analysis.analysis_id, "aggregate", worker_id="w", ttl_ms=1000, now=now
    )
    assert lease is not None
    assert pg_repo.start_stage(lease, now=now)
    assert pg_repo.fail_stage(
        lease, terminal=True, code="RESOURCE_STATE", message="stopped", now=now
    )
