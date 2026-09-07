"""Local poll vs Celery dispatch produce the same measured report fields."""

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from tests.factories import DIGEST, make_artifact, make_availability, make_report, make_video
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.errors import ingest_error
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState, StageCommand
from cine_analyzer.domain.report import AnalysisReport, StageAvailability
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings
from cine_analyzer.worker.commands import build_stage_command
from cine_analyzer.worker.dispatch import (
    bind_runtime,
    execute_orchestrate,
    execute_stage_payload,
    reset_runtime,
)
from cine_analyzer.worker.runner import process_once
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


def _measured(report: AnalysisReport) -> dict[str, object]:
    data = report.model_dump(mode="json")

    def strip(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: strip(item)
                for key, item in value.items()
                if key not in {"started_at", "completed_at", "code_revision", "analysis_id"}
            }
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return strip(data)  # type: ignore[return-value]


def _seed(jobs: MemoryJobRepository) -> AnalysisRecord:
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
            state=AnalysisState.QUEUED,
        )
    )
    jobs.record_config(analysis.analysis_id, AnalysisConfig())
    jobs.ensure_pending_stages(analysis.analysis_id)
    return analysis


def test_local_and_celery_dispatch_match_measured_fields(tmp_path: Path) -> None:
    settings = Settings(artifact_root=tmp_path / "art", worker_id="test-worker")
    local_jobs = MemoryJobRepository()
    local_store = MemoryStore(tmp_path / "local")
    local_analysis = _seed(local_jobs)
    local_stage = _OkStage(local_jobs, local_store)
    local_services = WorkerServices(store=local_store, sampling=local_stage, report=local_stage)
    assert process_once(jobs=local_jobs, services=local_services, settings=settings)
    local_row = local_jobs.get_artifact_by_storage_key(
        f"analyses/{local_analysis.analysis_id.hex}/report.json"
    )
    assert local_row is not None
    local_report = AnalysisReport.model_validate_json(
        local_store.local_path(local_row.storage_key).read_bytes()
    )

    celery_jobs = MemoryJobRepository()
    celery_store = MemoryStore(tmp_path / "celery")
    celery_analysis = _seed(celery_jobs)
    celery_stage = _OkStage(celery_jobs, celery_store)
    queued: list[tuple[StageCommand, float | None]] = []
    bind_runtime(
        jobs=celery_jobs,
        services=WorkerServices(store=celery_store, sampling=celery_stage, report=celery_stage),
        settings=settings,
        enqueue=lambda command, countdown: queued.append((command, countdown)),
    )
    execute_orchestrate(
        build_stage_command(
            analysis_id=celery_analysis.analysis_id,
            stage_name="orchestrate",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            trace_id="eq",
        ).model_dump(mode="json")
    )
    while queued:
        command, _countdown = queued.pop(0)
        execute_stage_payload(command.model_dump(mode="json"))
    celery_row = celery_jobs.get_artifact_by_storage_key(
        f"analyses/{celery_analysis.analysis_id.hex}/report.json"
    )
    assert celery_row is not None
    celery_report = AnalysisReport.model_validate_json(
        celery_store.local_path(celery_row.storage_key).read_bytes()
    )
    assert _measured(local_report) == _measured(celery_report)
    reset_runtime()


def test_worker_loss_after_artifact_write_retries_without_duplicate(
    tmp_path: Path,
) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    analysis = _seed(jobs)
    jobs.set_analysis_state(
        analysis.analysis_id, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    writes = {"n": 0}

    class _WriteThenCrash:
        def execute(self, **kwargs: object) -> None:
            record = kwargs["analysis"]
            key = f"analyses/{record.analysis_id.hex}/report.json"  # type: ignore[union-attr]
            store.put_bytes(b'{"ok":true}', storage_key=key)
            jobs.insert_artifact(make_artifact(kind="analysis_report"), storage_key=key)
            writes["n"] += 1
            if writes["n"] == 1:
                raise ingest_error(
                    "RESOURCE_STATE",
                    "lost after write",
                    request_id="req",
                    retryable=True,
                    stage="report",
                )

    queued: list[tuple[StageCommand, float | None]] = []
    crash = _WriteThenCrash()
    bind_runtime(
        jobs=jobs,
        services=WorkerServices(store=store, sampling=crash, report=crash),  # type: ignore[arg-type]
        settings=Settings(artifact_root=tmp_path, worker_id="w", stage_retry_max_attempts=3),
        enqueue=lambda command, countdown: queued.append((command, countdown)),
    )
    execute_stage_payload(
        build_stage_command(
            analysis_id=analysis.analysis_id,
            stage_name="sampling",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            trace_id="loss",
        ).model_dump(mode="json")
    )
    attempts = [
        run for run in jobs.list_stage_runs(analysis.analysis_id) if run.stage_name == "sampling"
    ]
    assert any(run.state.value == "FAILED_RETRYABLE" for run in attempts)
    assert store.contains(f"analyses/{analysis.analysis_id.hex}/report.json")
    execute_stage_payload(
        build_stage_command(
            analysis_id=analysis.analysis_id,
            stage_name="sampling",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            trace_id="loss",
        ).model_dump(mode="json")
    )
    assert writes["n"] == 2
    matching = [
        item
        for item in jobs._artifacts.values()
        if item.storage_key == f"analyses/{analysis.analysis_id.hex}/report.json"
    ]
    assert matching
    reset_runtime()
