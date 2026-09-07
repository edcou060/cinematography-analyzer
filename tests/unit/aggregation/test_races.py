"""Lease races against the in-memory repository."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_artifact, make_video
from tests.unit.aggregation.memory_jobs import MemoryJobRepository

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState, StageState
from cine_analyzer.ports.control import StageLease
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord


def _video(repo: MemoryJobRepository) -> VideoRecord:
    record = VideoRecord(
        metadata=make_video(content_sha256=DIGEST),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    return repo.insert_video(record)


def _queued(repo: MemoryJobRepository, video: VideoRecord, key: str) -> AnalysisRecord:
    return repo.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=key,
            state=AnalysisState.QUEUED,
        )
    )


def test_duplicate_analysis_creation_returns_the_original() -> None:
    repo = MemoryJobRepository()
    video = _video(repo)
    key = sha256(b"dup").hexdigest()
    first = _queued(repo, video, key)
    second = _queued(repo, video, key)
    assert second.analysis_id == first.analysis_id


def test_two_stage_claimants_only_one_wins() -> None:
    repo = MemoryJobRepository()
    video = _video(repo)
    analysis = _queued(repo, video, sha256(b"race").hexdigest())
    repo.ensure_pending_stages(analysis.analysis_id)
    now = datetime.now(tz=UTC)

    def claim() -> object:
        return repo.acquire_stage(
            analysis.analysis_id, "sampling", worker_id="w", ttl_ms=5_000, now=now
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(claim)
        second = pool.submit(claim)
        results = [first.result(), second.result()]
    wins = [item for item in results if item is not None]
    assert len(wins) == 1


def test_stale_completion_cannot_overwrite_a_new_lease() -> None:
    repo = MemoryJobRepository()
    video = _video(repo)
    analysis = _queued(repo, video, sha256(b"stale").hexdigest())
    repo.ensure_pending_stages(analysis.analysis_id)
    early = datetime.now(tz=UTC) - timedelta(seconds=30)
    stale = repo.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="old", ttl_ms=1, now=early
    )
    assert stale is not None
    assert repo.start_stage(stale, now=early)
    now = datetime.now(tz=UTC)
    fresh = repo.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="new", ttl_ms=5_000, now=now
    )
    assert fresh is not None
    assert repo.start_stage(fresh, now=now)
    assert repo.complete_stage(stale, now=now) is False
    assert repo.complete_stage(fresh, now=now) is True
    runs = repo.list_stage_runs(analysis.analysis_id)
    assert runs[-1].state is StageState.SUCCEEDED


def test_retry_attempt_is_a_new_pending_row() -> None:
    repo = MemoryJobRepository()
    video = _video(repo)
    analysis = _queued(repo, video, sha256(b"retry").hexdigest())
    repo.ensure_pending_stages(analysis.analysis_id)
    now = datetime.now(tz=UTC)
    lease = repo.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="w", ttl_ms=5_000, now=now
    )
    assert lease is not None
    assert repo.start_stage(lease, now=now)
    assert repo.fail_stage(lease, terminal=False, code="RESOURCE_STATE", message="busy", now=now)
    retry = repo.insert_retry_attempt(analysis.analysis_id, "sampling")
    assert retry.attempt == 2
    assert retry.state is StageState.PENDING
    again = repo.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="w", ttl_ms=5_000, now=now
    )
    assert again is not None
    assert again.attempt == 2


def test_heartbeat_and_cancel_and_artifact_helpers() -> None:
    repo = MemoryJobRepository()
    video = _video(repo)
    analysis = _queued(repo, video, sha256(b"misc").hexdigest())
    repo.ensure_pending_stages(analysis.analysis_id, ())
    repo.ensure_pending_stages(analysis.analysis_id)
    repo.record_config(analysis.analysis_id, AnalysisConfig())
    now = datetime.now(tz=UTC)
    claimed = repo.claim_queued(worker_id="w", now=now)
    assert claimed is not None
    lease = repo.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="w", ttl_ms=5_000, now=now
    )
    assert lease is not None
    assert repo.start_stage(lease, now=now)
    assert repo.heartbeat_stage(lease, ttl_ms=5_000, now=now)
    assert repo.heartbeat_stage(lease, ttl_ms=5_000, now=now) is True
    stale_token = lease
    assert repo.cancel_stage(analysis.analysis_id, "report", 1)
    assert repo.cancel_stage(analysis.analysis_id, "report", 1) is False
    ref = make_artifact()
    repo.insert_artifact(ref, storage_key="ee/" + "e" * 64)
    repo.insert_artifact(ref, storage_key="ee/" + "e" * 64)
    assert repo.get_artifact(ref.artifact_id) is not None
    assert repo.get_artifact_by_storage_key("ee/" + "e" * 64) is not None
    assert repo.get_artifact_by_storage_key("missing") is None
    repo.link_artifact(ref.artifact_id, analysis_id=analysis.analysis_id)
    repo.link_artifact(uuid4(), analysis_id=analysis.analysis_id)
    repo.ping()
    repo.close()
    canceled = repo.request_cancel(analysis.analysis_id, now=now)
    assert canceled is not None
    assert canceled.state is AnalysisState.CANCEL_REQUESTED
    assert repo.request_cancel(uuid4(), now=now) is None
    assert (
        repo.set_analysis_state(
            analysis.analysis_id,
            expected=AnalysisState.SUCCEEDED,
            target=AnalysisState.QUEUED,
        )
        is False
    )
    with pytest.raises(AdapterError):
        repo.claim_queued(worker_id="", now=now)
    repo.fail_reads = True
    with pytest.raises(AdapterError):
        repo.ping()
    _ = stale_token


def test_memory_rejects_colliding_primary_keys_and_reclaims_running() -> None:
    repo = MemoryJobRepository()
    video = _video(repo)
    colliding = VideoRecord(
        metadata=make_video(video_id=video.metadata.video_id, content_sha256="b" * 64),
        original_storage_key="cc/" + "c" * 64,
        probe_storage_key="dd/" + "d" * 64,
    )
    with pytest.raises(AdapterError):
        repo.insert_video(colliding)
    first = _queued(repo, video, sha256(b"ident-a").hexdigest())
    with pytest.raises(AdapterError):
        repo.insert_analysis(
            AnalysisRecord(
                analysis_id=uuid4(),
                video_id=video.metadata.video_id,
                configuration_hash=DIGEST,
                pipeline_version="0.1.0",
                analysis_key=sha256(b"ident-b").hexdigest(),
                state=AnalysisState.QUEUED,
            )
        )
    assert repo.get_analysis(first.analysis_id) is not None
    assert repo.get_analysis(uuid4()) is None
    assert repo.get_analysis_by_key("missing") is None
    now = datetime.now(tz=UTC)
    claimed = repo.claim_queued(worker_id="w", now=now)
    assert claimed is not None
    again = repo.claim_queued(worker_id="w", now=now)
    assert again is not None
    assert again.state is AnalysisState.RUNNING
    other_video = VideoRecord(
        metadata=make_video(video_id=uuid4(), content_sha256="c" * 64),
        original_storage_key="ee/" + "e" * 64,
        probe_storage_key="ff/" + "f" * 64,
    )
    repo.insert_video(other_video)
    queued = _queued(repo, other_video, sha256(b"to-cancel").hexdigest())
    canceled = repo.request_cancel(queued.analysis_id, now=now)
    assert canceled is not None
    assert canceled.state is AnalysisState.CANCELED
    assert repo.get_video_by_hash(DIGEST) is not None
    assert repo.get_shot(first.analysis_id, uuid4()) is None
    assert repo.get_report_summary(first.analysis_id) is None
    fake = StageLease(
        stage_run_id=uuid4(),
        analysis_id=first.analysis_id,
        stage_name="sampling",
        attempt=1,
        token=uuid4(),
        worker_id="w",
        expires_at=now,
    )
    assert repo.heartbeat_stage(fake, ttl_ms=1, now=now) is False
    assert repo.start_stage(fake, now=now) is False
    assert (
        repo.acquire_stage(first.analysis_id, "sampling", worker_id="w", ttl_ms=1, now=now) is None
    )
