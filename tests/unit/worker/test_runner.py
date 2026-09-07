"""Worker claims queued work, honors cancel, and fails missing inputs."""

import io
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_artifact, make_availability, make_report, make_video
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.errors import ingest_error
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings
from cine_analyzer.worker.runner import _run_named_stage, process_once, run_worker
from cine_analyzer.worker.services import WorkerServices, build_worker_services


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
        raise ingest_error(
            "RESOURCE_STATE",
            "temporary failure",
            request_id="req",
            retryable=True,
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(artifact_root=tmp_path / "art", worker_id="test-worker", worker_poll_ms=1)


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
    return analysis


def test_process_once_is_idle_when_the_queue_is_empty() -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(Path())
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    assert process_once(jobs=jobs, services=services, settings=Settings()) is False


def test_process_once_runs_stages_and_aggregates(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    sampling = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=sampling, report=sampling)  # type: ignore[arg-type]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state in {AnalysisState.SUCCEEDED, AnalysisState.PARTIAL}


def test_process_once_honors_cancel(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    jobs.set_analysis_state(
        analysis.analysis_id,
        expected=AnalysisState.QUEUED,
        target=AnalysisState.RUNNING,
    )
    jobs.set_analysis_state(
        analysis.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.CANCEL_REQUESTED,
    )
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state is AnalysisState.CANCELED


def test_process_once_maps_stage_failure(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    boom = _BoomStage()
    services = WorkerServices(store=store, sampling=boom, report=boom)  # type: ignore[arg-type]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None
    assert job.record.state is AnalysisState.FAILED


def test_run_worker_once_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    jobs = MemoryJobRepository()
    store = MemoryStore(Path())
    boom = _BoomStage()
    services = WorkerServices(store=store, sampling=boom, report=boom)  # type: ignore[arg-type]
    code = run_worker(
        once=True,
        stdout=stdout,
        stderr=stderr,
        jobs=jobs,
        services=services,
    )
    assert code == 0
    assert "idle" in stdout.getvalue()
    monkeypatch.setenv("CINE_LOG_LEVEL", "chatty")
    failed = run_worker(once=True, stdout=io.StringIO(), stderr=io.StringIO())
    assert failed == 1


def test_run_worker_max_loops_sleeps_when_idle() -> None:
    slept: list[float] = []
    jobs = MemoryJobRepository()
    store = MemoryStore(Path())
    boom = _BoomStage()
    services = WorkerServices(store=store, sampling=boom, report=boom)  # type: ignore[arg-type]
    code = run_worker(
        once=False,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        jobs=jobs,
        services=services,
        max_loops=2,
        sleep=slept.append,
    )
    assert code == 0
    assert slept == [Settings().worker_poll_ms / 1000]


def test_run_worker_without_url_fails() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_worker(once=True, stdout=stdout, stderr=stderr)
    assert code == 1
    assert "CINE_DATABASE_URL" in stderr.getvalue()


def test_run_worker_writes_processed_and_closes_owned_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    stdout = io.StringIO()
    code = run_worker(
        once=True,
        stdout=stdout,
        stderr=io.StringIO(),
        jobs=jobs,
        services=services,
    )
    assert code == 0
    assert "processed" in stdout.getvalue()
    job = jobs.load_job(analysis.analysis_id)
    assert job is not None

    created: list[object] = []

    class _Owned:
        def __init__(self, url: str) -> None:
            del url
            created.append(self)
            self.closed = False

        def close(self) -> None:
            self.closed = True

        def claim_queued(self, **kwargs: object) -> None:
            del kwargs

    monkeypatch.setenv("CINE_DATABASE_URL", "postgresql+pg8000://cine:@127.0.0.1:1/cine")
    monkeypatch.setattr("cine_analyzer.worker.runner.PostgresJobRepository", _Owned)
    owned_out = io.StringIO()
    owned_code = run_worker(
        once=True,
        stdout=owned_out,
        stderr=io.StringIO(),
        services=services,
    )
    assert owned_code == 0
    assert created[0].closed is True
    assert "idle" in owned_out.getvalue()


def test_run_worker_refuses_celery_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    stderr = io.StringIO()
    code = run_worker(once=True, stdout=io.StringIO(), stderr=stderr)
    assert code == 1
    assert "celery-worker" in stderr.getvalue()


def test_process_once_missing_inputs_and_lease_failures(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
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
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True
    loaded = jobs.load_job(orphan.analysis_id)
    assert loaded is not None
    assert loaded.record.state is AnalysisState.FAILED

    analysis = _seed(jobs)
    jobs.acquire_stage = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True
    after = jobs.load_job(analysis.analysis_id)
    assert after is not None
    assert after.record.state is AnalysisState.FAILED


def test_process_once_start_and_complete_false_and_cancel_after_sampling(
    tmp_path: Path,
) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    jobs.start_stage = lambda *_args, **_kwargs: False  # type: ignore[method-assign]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True

    jobs2 = MemoryJobRepository()
    analysis2 = _seed(jobs2)
    stage2 = _OkStage(jobs2, store)
    services2 = WorkerServices(store=store, sampling=stage2, report=stage2)  # type: ignore[arg-type]
    jobs2.complete_stage = lambda *_args, **_kwargs: False  # type: ignore[method-assign]
    assert process_once(jobs=jobs2, services=services2, settings=_settings(tmp_path)) is True
    still = jobs2.load_job(analysis2.analysis_id)
    assert still is not None
    assert still.record.state is AnalysisState.RUNNING

    jobs3 = MemoryJobRepository()
    analysis3 = _seed(jobs3)

    class _CancelAfter:
        def execute(self, **kwargs: object) -> None:
            record = kwargs["analysis"]
            jobs3.set_analysis_state(
                record.analysis_id,  # type: ignore[union-attr]
                expected=AnalysisState.RUNNING,
                target=AnalysisState.CANCEL_REQUESTED,
            )
            check = kwargs.get("cancel_check")
            if callable(check):
                check()

    services3 = WorkerServices(
        store=store,
        sampling=_CancelAfter(),  # type: ignore[arg-type]
        report=stage2,
    )
    assert process_once(jobs=jobs3, services=services3, settings=_settings(tmp_path)) is True
    canceled = jobs3.load_job(analysis3.analysis_id)
    assert canceled is not None
    assert canceled.record.state is AnalysisState.CANCELED

    jobs4 = MemoryJobRepository()
    analysis4 = _seed(jobs4)
    store4 = MemoryStore(tmp_path / "post")

    class _MarkCancel:
        def execute(self, **kwargs: object) -> None:
            record = kwargs["analysis"]
            jobs4.set_analysis_state(
                record.analysis_id,  # type: ignore[union-attr]
                expected=AnalysisState.RUNNING,
                target=AnalysisState.CANCEL_REQUESTED,
            )

    services4 = WorkerServices(
        store=store4,
        sampling=_MarkCancel(),  # type: ignore[arg-type]
        report=_OkStage(jobs4, store4),  # type: ignore[arg-type]
    )
    assert process_once(jobs=jobs4, services=services4, settings=_settings(tmp_path)) is True
    after_sample = jobs4.load_job(analysis4.analysis_id)
    assert after_sample is not None
    assert after_sample.record.state is AnalysisState.CANCELED

    jobs5 = MemoryJobRepository()
    analysis5 = _seed(jobs5)
    store5 = MemoryStore(tmp_path / "report-cancel")

    class _CancelOnReport:
        def execute(self, **kwargs: object) -> None:
            record = kwargs["analysis"]
            jobs5.set_analysis_state(
                record.analysis_id,  # type: ignore[union-attr]
                expected=AnalysisState.RUNNING,
                target=AnalysisState.CANCEL_REQUESTED,
            )

    services5 = WorkerServices(
        store=store5,
        sampling=_OkStage(jobs5, store5),  # type: ignore[arg-type]
        report=_CancelOnReport(),  # type: ignore[arg-type]
    )
    assert process_once(jobs=jobs5, services=services5, settings=_settings(tmp_path)) is True
    after_report = jobs5.load_job(analysis5.analysis_id)
    assert after_report is not None
    assert after_report.record.state is AnalysisState.CANCELED
    _ = analysis


def test_process_once_skips_succeeded_sampling_and_terminal_failure(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    now = datetime.now(tz=UTC)
    lease = jobs.acquire_stage(
        analysis.analysis_id, "sampling", worker_id="test-worker", ttl_ms=1000, now=now
    )
    assert lease is not None
    assert jobs.start_stage(lease, now=now)
    assert jobs.complete_stage(lease, now=now)
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True

    jobs2 = MemoryJobRepository()
    analysis2 = _seed(jobs2)

    class _Terminal:
        def execute(self, **kwargs: object) -> None:
            del kwargs
            raise ingest_error(
                "MEDIA_UNREADABLE",
                "unreadable",
                request_id="req",
                retryable=False,
            )

    services2 = WorkerServices(store=store, sampling=_Terminal(), report=stage)  # type: ignore[arg-type]
    assert process_once(jobs=jobs2, services=services2, settings=_settings(tmp_path)) is True
    failed = jobs2.load_job(analysis2.analysis_id)
    assert failed is not None
    assert failed.record.state is AnalysisState.FAILED


def test_build_worker_services_constructs(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    services = build_worker_services(_settings(tmp_path), jobs)
    assert services.sampling is not None
    assert services.report is not None


def test_run_worker_stops_after_processed_max_loops(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    _seed(jobs)
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    slept: list[float] = []
    code = run_worker(
        once=False,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        jobs=jobs,
        services=services,
        max_loops=2,
        sleep=slept.append,
    )
    assert code == 0
    assert slept == []


def test_cancel_after_report_and_at_stage_start(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)

    class _CancelOnReport(_OkStage):
        def execute(self, **kwargs: object) -> None:
            super().execute(**kwargs)
            record = kwargs["analysis"]
            jobs.set_analysis_state(
                record.analysis_id,  # type: ignore[union-attr]
                expected=AnalysisState.RUNNING,
                target=AnalysisState.CANCEL_REQUESTED,
            )

    sampling = _OkStage(jobs, store)
    services = WorkerServices(
        store=store,
        sampling=sampling,
        report=_CancelOnReport(jobs, store),  # type: ignore[arg-type]
    )
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True
    loaded = jobs.load_job(analysis.analysis_id)
    assert loaded is not None
    assert loaded.record.state is AnalysisState.CANCELED

    jobs2 = MemoryJobRepository()
    analysis2 = _seed(jobs2)
    jobs2.set_analysis_state(
        analysis2.analysis_id,
        expected=AnalysisState.QUEUED,
        target=AnalysisState.RUNNING,
    )
    jobs2.set_analysis_state(
        analysis2.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.CANCEL_REQUESTED,
    )
    assert (
        _run_named_stage(
            jobs2,
            analysis2.analysis_id,
            "sampling",
            worker_id="test-worker",
            ttl_ms=1000,
            now=datetime.now(tz=UTC),
            work=lambda: None,
        )
        is False
    )


def test_process_once_returns_when_report_complete_fails(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    _seed(jobs)
    stage = _OkStage(jobs, store)
    services = WorkerServices(store=store, sampling=stage, report=stage)  # type: ignore[arg-type]
    original = jobs.complete_stage
    calls = {"n": 0}

    def after_sampling(*args: object, **kwargs: object) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            return original(*args, **kwargs)
        return False

    jobs.complete_stage = after_sampling  # type: ignore[method-assign]
    assert process_once(jobs=jobs, services=services, settings=_settings(tmp_path)) is True
