"""Celery/local dispatch: orchestrate, stage run, retry, GPU, critic."""

from collections.abc import Iterator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_artifact, make_availability, make_report, make_video
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.errors import AdapterError, ingest_error
from cine_analyzer.domain.config import AnalysisConfig, CriticConfig
from cine_analyzer.domain.jobs import AnalysisState, StageCommand
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings
from cine_analyzer.worker.commands import build_stage_command
from cine_analyzer.worker.dispatch import (
    bind_runtime,
    execute_critic_payload,
    execute_gpu_spatial_payload,
    execute_orchestrate,
    execute_stage_payload,
    reset_runtime,
    runtime_jobs,
    runtime_services,
    runtime_settings,
)
from cine_analyzer.worker.lifecycle import initialize_gpu_detector, reset_gpu_detector
from cine_analyzer.worker.services import WorkerServices


class _OkStage:
    def __init__(self, jobs: MemoryJobRepository, store: MemoryStore) -> None:
        self._jobs = jobs
        self._store = store

    def execute(self, **kwargs: object) -> None:
        check = kwargs.get("cancel_check")
        if callable(check):
            check()
        analysis = kwargs["analysis"]
        report = make_report(
            analysis_id=analysis.analysis_id,  # type: ignore[union-attr]
            availability=make_availability(
                chromatic=StageAvailability.COMPLETE,
                motion=StageAvailability.COMPLETE,
                tension=StageAvailability.COMPLETE,
            ),
        )
        key = f"analyses/{analysis.analysis_id.hex}/report.json"  # type: ignore[union-attr]
        self._store.put_bytes(report.model_dump_json().encode("utf-8"), storage_key=key)
        self._jobs.insert_artifact(make_artifact(kind="analysis_report"), storage_key=key)


class _BoomStage:
    def execute(self, **kwargs: object) -> None:
        del kwargs
        raise ingest_error("RESOURCE_STATE", "temporary failure", request_id="req", retryable=True)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    payload: dict[str, object] = {
        "artifact_root": tmp_path / "art",
        "worker_id": "test-worker",
        "stage_retry_base_ms": 10,
        "stage_retry_cap_ms": 20,
        "stage_retry_max_attempts": 3,
    }
    payload.update(overrides)
    return Settings.model_validate(payload)


def _seed(
    jobs: MemoryJobRepository, *, state: AnalysisState = AnalysisState.QUEUED
) -> AnalysisRecord:
    digest = sha256(uuid4().bytes).hexdigest()
    video = VideoRecord(
        metadata=make_video(video_id=uuid4(), content_sha256=digest),
        original_storage_key=digest[:2] + "/" + digest,
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
            state=state,
        )
    )
    jobs.record_config(analysis.analysis_id, AnalysisConfig())
    jobs.ensure_pending_stages(analysis.analysis_id)
    return analysis


def _bind(
    tmp_path: Path,
    jobs: MemoryJobRepository,
    store: MemoryStore,
    *,
    sampling: object | None = None,
    report: object | None = None,
    settings: Settings | None = None,
) -> list[tuple[StageCommand, float | None]]:
    queued: list[tuple[StageCommand, float | None]] = []
    stage = _OkStage(jobs, store) if sampling is None else sampling
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    bind_runtime(
        jobs=jobs,
        services=services,
        settings=_settings(tmp_path) if settings is None else settings,
        enqueue=lambda command, countdown: queued.append((command, countdown)),
    )
    return queued


def _cmd(analysis_id: object, stage: str) -> dict[str, object]:
    return build_stage_command(
        analysis_id=analysis_id,  # type: ignore[arg-type]
        stage_name=stage,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        trace_id="trace",
    ).model_dump(mode="json")


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    reset_runtime()
    reset_gpu_detector()
    yield
    reset_runtime()
    reset_gpu_detector()


def test_orchestrate_missing_terminal_cancel_and_enqueue(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    queued = _bind(tmp_path, jobs, store)
    execute_orchestrate(_cmd(uuid4(), "orchestrate"))
    assert queued == []

    analysis = _seed(jobs)
    execute_orchestrate(_cmd(analysis.analysis_id, "orchestrate"))
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state is AnalysisState.RUNNING
    assert queued[0][0].stage_name == "sampling"

    jobs.set_analysis_state(
        analysis.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.SUCCEEDED,
    )
    queued.clear()
    execute_orchestrate(_cmd(analysis.analysis_id, "orchestrate"))
    assert queued == []

    canceled = _seed(jobs)
    jobs.set_analysis_state(
        canceled.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    jobs.set_analysis_state(
        canceled.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.CANCEL_REQUESTED,
    )
    execute_orchestrate(_cmd(canceled.analysis_id, "orchestrate"))
    loaded = jobs.load_job(canceled.analysis_id)
    assert loaded is not None
    assert loaded.record.state is AnalysisState.CANCELED

    leased = _seed(jobs)
    jobs.set_analysis_state(
        leased.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    assert jobs.acquire_stage(
        leased.analysis_id,
        "sampling",
        worker_id="w",
        ttl_ms=60_000,
        now=datetime.now(tz=UTC),
    )
    queued.clear()
    execute_orchestrate(_cmd(leased.analysis_id, "orchestrate"))
    assert queued == []


def test_execute_stage_runs_then_enqueues_next(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    queued = _bind(tmp_path, jobs, store)
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    assert queued[-1][0].stage_name == "report"
    execute_stage_payload(_cmd(analysis.analysis_id, "report"))
    assert queued[-1][0].stage_name == "aggregate"
    execute_stage_payload(_cmd(analysis.analysis_id, "aggregate"))
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state in {AnalysisState.SUCCEEDED, AnalysisState.PARTIAL}
    queued.clear()
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    assert queued == []


def test_execute_stage_rejects_unknown_and_missing_inputs(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    _bind(tmp_path, jobs, store)
    with pytest.raises(ValueError, match="unsupported CPU stage"):
        execute_stage_payload(_cmd(uuid4(), "spatial"))
    execute_stage_payload(_cmd(uuid4(), "sampling"))
    orphan = jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=uuid4(),
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key=sha256(b"orphan").hexdigest(),
            state=AnalysisState.QUEUED,
        )
    )
    jobs.record_config(orphan.analysis_id, AnalysisConfig())
    jobs.ensure_pending_stages(orphan.analysis_id)
    jobs.set_analysis_state(
        orphan.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_stage_payload(_cmd(orphan.analysis_id, "sampling"))
    loaded = jobs.load_job(orphan.analysis_id)
    assert loaded is not None
    assert loaded.record.state is AnalysisState.FAILED


def test_retryable_failure_re_enqueues(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    queued = _bind(tmp_path, jobs, store, sampling=_BoomStage(), report=_BoomStage())
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    assert queued[-1][0].stage_name == "sampling"
    delay = queued[-1][1]
    assert delay is not None
    assert delay > 0
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state is AnalysisState.RUNNING


def test_cancel_during_stage(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)

    class _Cancel:
        def execute(self, **kwargs: object) -> None:
            record = kwargs["analysis"]
            jobs.set_analysis_state(
                record.analysis_id,  # type: ignore[union-attr]
                expected=AnalysisState.RUNNING,
                target=AnalysisState.CANCEL_REQUESTED,
            )
            check = kwargs.get("cancel_check")
            if callable(check):
                check()

    queued = _bind(tmp_path, jobs, store, sampling=_Cancel())
    del queued
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    loaded = jobs.load_job(analysis.analysis_id)
    assert loaded is not None
    assert loaded.record.state is AnalysisState.CANCELED


def test_pre_stage_cancel_and_gpu_critic(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    _bind(tmp_path, jobs, store)
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    jobs.set_analysis_state(
        analysis.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.CANCEL_REQUESTED,
    )
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    loaded = jobs.load_job(analysis.analysis_id)
    assert loaded is not None
    assert loaded.record.state is AnalysisState.CANCELED

    with pytest.raises(ValueError, match="stage_name 'spatial'"):
        execute_gpu_spatial_payload(_cmd(analysis.analysis_id, "sampling"))
    with pytest.raises(AdapterError, match="has not initialized"):
        execute_gpu_spatial_payload(_cmd(analysis.analysis_id, "spatial"))
    initialize_gpu_detector(Settings())
    execute_gpu_spatial_payload(_cmd(analysis.analysis_id, "spatial"))
    with pytest.raises(ValueError, match="stage_name 'critic'"):
        execute_critic_payload(_cmd(analysis.analysis_id, "sampling"))
    execute_critic_payload(_cmd(analysis.analysis_id, "critic"))
    assert runtime_jobs() is jobs
    assert runtime_services() is not None
    assert runtime_settings() is not None


def test_terminal_media_failure_fails_the_analysis(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)

    class _Terminal:
        def execute(self, **kwargs: object) -> None:
            del kwargs
            raise ingest_error(
                "MEDIA_UNREADABLE",
                "corrupt",
                request_id="req",
                retryable=False,
            )

    _bind(tmp_path, jobs, store, sampling=_Terminal())
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state is AnalysisState.FAILED


def test_require_runtime_without_database(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_runtime()
    monkeypatch.setattr("cine_analyzer.settings.load_settings", Settings)
    with pytest.raises(RuntimeError, match="CINE_DATABASE_URL"):
        execute_orchestrate(_cmd(uuid4(), "orchestrate"))


def test_require_runtime_builds_services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_runtime()
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    settings = _settings(tmp_path)
    settings_with_url = Settings(
        artifact_root=tmp_path / "art",
        database_url="postgresql+pg8000://cine:@127.0.0.1:1/cine",
        worker_id="w",
    )
    monkeypatch.setattr("cine_analyzer.settings.load_settings", lambda: settings_with_url)
    monkeypatch.setattr(
        "cine_analyzer.adapters.persistence.postgres.PostgresJobRepository",
        lambda url: jobs,
    )
    monkeypatch.setattr(
        "cine_analyzer.worker.services.build_worker_services",
        lambda _settings, _jobs: WorkerServices(
            store=store, sampling=_OkStage(jobs, store), report=_OkStage(jobs, store)
        ),
    )
    del settings
    execute_orchestrate(_cmd(uuid4(), "orchestrate"))
    assert runtime_jobs() is jobs


def test_terminal_retryable_marks_failed(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    queued = _bind(tmp_path, jobs, store, sampling=_BoomStage())
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    settings = _settings(tmp_path)
    bind_runtime(
        jobs=jobs,
        services=WorkerServices(store=store, sampling=_BoomStage(), report=_BoomStage()),  # type: ignore[arg-type]
        settings=Settings(
            artifact_root=tmp_path / "art",
            worker_id="test-worker",
            stage_retry_max_attempts=1,
            stage_retry_base_ms=10,
            stage_retry_cap_ms=20,
        ),
        enqueue=lambda command, countdown: queued.append((command, countdown)),
    )
    del settings
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state is AnalysisState.FAILED


def test_enqueue_next_missing_job(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    _bind(tmp_path, jobs, store)
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    from cine_analyzer.worker import dispatch as module

    module._enqueue_next(uuid4(), "trace", jobs=jobs)


def test_critic_after_aggregate_does_not_fail_analysis(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    jobs.record_config(analysis.analysis_id, AnalysisConfig(critic=CriticConfig(enabled=True)))
    queued = _bind(tmp_path, jobs, store, settings=_settings(tmp_path, critic_backend="fake"))
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_stage_payload(_cmd(analysis.analysis_id, "sampling"))
    execute_stage_payload(_cmd(analysis.analysis_id, "report"))
    execute_stage_payload(_cmd(analysis.analysis_id, "aggregate"))
    assert queued[-1][0].stage_name == "critic"
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state in {AnalysisState.SUCCEEDED, AnalysisState.PARTIAL}
    execute_critic_payload(_cmd(analysis.analysis_id, "critic"))
    latest = jobs.load_job(analysis.analysis_id)
    assert latest is not None
    assert latest.record.state is job.record.state
    stored = jobs.get_latest_critique(analysis.analysis_id)
    assert stored is not None
    assert stored.critique.text is not None
    execute_critic_payload(_cmd(uuid4(), "critic"))
    from cine_analyzer.worker import dispatch as module

    module._maybe_enqueue_critic(
        queued[-1][0],
        jobs=jobs,
        settings=_settings(tmp_path, critic_backend="none"),
    )
    missing = build_stage_command(
        analysis_id=uuid4(),
        stage_name="aggregate",
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        trace_id="trace",
    )
    module._maybe_enqueue_critic(
        missing, jobs=jobs, settings=_settings(tmp_path, critic_backend="fake")
    )
    disabled = _seed(jobs)
    module._maybe_enqueue_critic(
        build_stage_command(
            analysis_id=disabled.analysis_id,
            stage_name="aggregate",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            trace_id="trace",
        ),
        jobs=jobs,
        settings=_settings(tmp_path, critic_backend="fake"),
    )


def test_orchestrate_vanishes_after_claim(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    queued = _bind(tmp_path, jobs, store)
    original = jobs.load_job

    def _load(analysis_id: object) -> object:
        job = original(analysis_id)  # type: ignore[arg-type]
        if job is not None and job.record.state is AnalysisState.RUNNING:
            return None
        return job

    jobs.load_job = _load  # type: ignore[method-assign]
    execute_orchestrate(_cmd(analysis.analysis_id, "orchestrate"))
    assert queued == []


def test_send_uses_enqueue_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    bind_runtime(
        jobs=jobs,
        services=WorkerServices(
            store=store, sampling=_OkStage(jobs, store), report=_OkStage(jobs, store)
        ),  # type: ignore[arg-type]
        settings=_settings(tmp_path),
        enqueue=None,
    )
    sent: list[StageCommand] = []
    monkeypatch.setattr(
        "cine_analyzer.worker.enqueue.enqueue_command",
        lambda command, countdown=None, settings=None: sent.append(command),
    )
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    execute_orchestrate(_cmd(analysis.analysis_id, "orchestrate"))
    assert sent[0].stage_name == "sampling"
