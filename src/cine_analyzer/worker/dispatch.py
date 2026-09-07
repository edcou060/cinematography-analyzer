"""Thin Celery/local dispatch: lease, run existing services, schedule from PostgreSQL."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from cine_analyzer.application.aggregation import persist_report_outcome
from cine_analyzer.application.errors import IngestError
from cine_analyzer.application.stage_execute import (
    StageOutcome,
    honor_cancel,
    run_leased_stage,
    should_cancel,
)
from cine_analyzer.domain.jobs import AnalysisState, StageCommand, StageState
from cine_analyzer.logging_setup import bind_context, get_logger
from cine_analyzer.observability.tracing import record_queue_wait, span
from cine_analyzer.ports.control import JobRepository
from cine_analyzer.settings import Settings
from cine_analyzer.worker.commands import build_stage_command, parse_stage_command
from cine_analyzer.worker.queues import queue_for_stage
from cine_analyzer.worker.schedule import next_runnable_stage

if TYPE_CHECKING:
    from cine_analyzer.worker.services import WorkerServices

__all__ = [
    "bind_runtime",
    "execute_critic_payload",
    "execute_gpu_spatial_payload",
    "execute_orchestrate",
    "execute_stage_payload",
    "reset_runtime",
    "runtime_jobs",
    "runtime_services",
    "runtime_settings",
]

_jobs: JobRepository | None = None
_services: "WorkerServices | None" = None
_settings: Settings | None = None
_enqueue: Callable[[StageCommand, float | None], None] | None = None


def bind_runtime(
    *,
    jobs: JobRepository,
    services: "WorkerServices",
    settings: Settings,
    enqueue: Callable[[StageCommand, float | None], None] | None = None,
) -> None:
    """Inject ports for tests and for a worker process that already built services."""
    global _jobs, _services, _settings, _enqueue
    _jobs = jobs
    _services = services
    _settings = settings
    _enqueue = enqueue


def reset_runtime() -> None:
    """Clear process-level ports. Tests only."""
    global _jobs, _services, _settings, _enqueue
    _jobs = None
    _services = None
    _settings = None
    _enqueue = None


def runtime_jobs() -> JobRepository | None:
    return _jobs


def runtime_services() -> "WorkerServices | None":
    return _services


def runtime_settings() -> Settings | None:
    return _settings


def execute_orchestrate(payload: dict[str, Any]) -> None:
    """Claim a queued analysis in PostgreSQL and enqueue the first runnable stage."""
    command = parse_stage_command(payload)
    jobs = _require_runtime()[1]
    job = jobs.load_job(command.analysis_id)
    if job is None:
        get_logger(__name__).warning("orchestrate.missing", analysis_id=str(command.analysis_id))
        return
    if job.record.state is AnalysisState.QUEUED:
        jobs.set_analysis_state(
            command.analysis_id,
            expected=AnalysisState.QUEUED,
            target=AnalysisState.RUNNING,
        )
        job = jobs.load_job(command.analysis_id)
        if job is None:
            return
    if should_cancel(jobs, command.analysis_id):
        honor_cancel(jobs, command.analysis_id)
        return
    if job.record.state in {
        AnalysisState.SUCCEEDED,
        AnalysisState.PARTIAL,
        AnalysisState.FAILED,
        AnalysisState.CANCELED,
    }:
        return
    nxt = next_runnable_stage(jobs.list_stage_runs(command.analysis_id))
    if nxt is None:
        return
    _send(
        build_stage_command(
            analysis_id=command.analysis_id,
            stage_name=nxt,
            configuration_hash=job.record.configuration_hash,
            pipeline_version=job.record.pipeline_version,
            trace_id=command.trace_id,
        )
    )


def execute_stage_payload(payload: dict[str, Any]) -> None:
    """Run sampling, report, or aggregate against PostgreSQL leases."""
    command = parse_stage_command(payload)
    settings, jobs, services = _require_runtime()
    if command.stage_name not in {"sampling", "report", "aggregate"}:
        message = f"unsupported CPU stage {command.stage_name!r}"
        raise ValueError(message)
    job = jobs.load_job(command.analysis_id)
    if job is None:
        return
    if should_cancel(jobs, command.analysis_id):
        honor_cancel(jobs, command.analysis_id)
        return
    video = jobs.get_video(job.record.video_id)
    if video is None:
        jobs.set_analysis_state(
            command.analysis_id,
            expected=AnalysisState.RUNNING,
            target=AnalysisState.FAILED,
            failure_code="ARTIFACT_MISSING",
            failure_message="the analysis inputs could not be loaded",
        )
        return
    request_id = command.trace_id
    wait_ms = int((datetime.now(tz=UTC) - command.requested_at).total_seconds() * 1000)
    record_queue_wait(queue=queue_for_stage(command.stage_name), wait_ms=wait_ms)

    def cancel_check() -> None:
        if should_cancel(jobs, command.analysis_id):
            raise _canceled(request_id, command.stage_name)

    def work() -> None:
        if command.stage_name == "sampling":
            services.sampling.execute(
                video=video,
                analysis=job.record,
                config=job.config,
                request_id=request_id,
                cancel_check=cancel_check,
            )
            return
        if command.stage_name == "report":
            services.report.execute(
                video=video,
                analysis=job.record,
                config=job.config,
                request_id=request_id,
                cancel_check=cancel_check,
            )
            return
        persist_report_outcome(jobs, services.store, command.analysis_id)

    now = datetime.now(tz=UTC)
    with (
        bind_context(
            request_id=request_id,
            trace_id=command.trace_id,
            analysis_id=str(command.analysis_id),
            stage=command.stage_name,
            worker_id=settings.worker_id,
        ),
        span("compute", stage=command.stage_name),
    ):
        try:
            outcome = run_leased_stage(
                jobs,
                command.analysis_id,
                command.stage_name,
                worker_id=settings.worker_id,
                ttl_ms=settings.lease_ttl_ms,
                now=now,
                work=work,
                max_attempts=settings.stage_retry_max_attempts,
            )
        except IngestError as error:
            _handle_stage_error(command, error, settings=settings, jobs=jobs)
            return
    if outcome is StageOutcome.SUCCEEDED:
        _enqueue_next(command.analysis_id, command.trace_id, jobs=jobs)
        if command.stage_name == "aggregate":
            _maybe_enqueue_critic(command, jobs=jobs, settings=settings)
        return
    if outcome is StageOutcome.CANCELED:
        return


def execute_gpu_spatial_payload(payload: dict[str, Any]) -> None:
    """Confirm the process-local detector is ready. Spatial metrics stay in report."""
    command = parse_stage_command(payload)
    if command.stage_name != "spatial":
        message = "gpu spatial tasks must use stage_name 'spatial'"
        raise ValueError(message)
    from cine_analyzer.worker.lifecycle import get_gpu_detector

    get_gpu_detector()
    get_logger(__name__).info(
        "gpu.spatial.ready",
        analysis_id=str(command.analysis_id),
        trace_id=command.trace_id,
    )


def execute_critic_payload(payload: dict[str, Any]) -> None:
    """Optional critic. Isolated from report completion; never fails the analysis."""
    command = parse_stage_command(payload)
    if command.stage_name != "critic":
        message = "critic tasks must use stage_name 'critic'"
        raise ValueError(message)
    settings, jobs, services = _require_runtime()
    from cine_analyzer.application.critic import persist_critique_for_job

    persist_critique_for_job(jobs, services.store, command.analysis_id, settings)


def _handle_stage_error(
    command: StageCommand,
    error: IngestError,
    *,
    settings: Settings,
    jobs: JobRepository,
) -> None:
    latest = [
        run
        for run in jobs.list_stage_runs(command.analysis_id)
        if run.stage_name == command.stage_name
    ]
    retryable = [run for run in latest if run.state is StageState.FAILED_RETRYABLE]
    if retryable:
        current = max(retryable, key=lambda run: run.attempt)
        from cine_analyzer.worker.retry import retry_countdown_seconds

        countdown = retry_countdown_seconds(
            current.attempt,
            base_ms=settings.stage_retry_base_ms,
            cap_ms=settings.stage_retry_cap_ms,
        )
        retry = build_stage_command(
            analysis_id=command.analysis_id,
            stage_name=command.stage_name,
            configuration_hash=command.configuration_hash,
            pipeline_version=command.pipeline_version,
            trace_id=command.trace_id,
            input_artifact_ids=command.input_artifact_ids,
        )
        _send(retry, countdown=countdown)
        return
    jobs.set_analysis_state(
        command.analysis_id,
        expected=AnalysisState.RUNNING,
        target=AnalysisState.FAILED,
        failure_code=error.safe.code,
        failure_message=error.safe.message,
    )


def _enqueue_next(analysis_id: UUID, trace_id: str, *, jobs: JobRepository) -> None:
    job = jobs.load_job(analysis_id)
    if job is None:
        return
    nxt = next_runnable_stage(jobs.list_stage_runs(analysis_id))
    if nxt is None:
        return
    _send(
        build_stage_command(
            analysis_id=analysis_id,
            stage_name=nxt,
            configuration_hash=job.record.configuration_hash,
            pipeline_version=job.record.pipeline_version,
            trace_id=trace_id,
        )
    )


def _maybe_enqueue_critic(
    command: StageCommand, *, jobs: JobRepository, settings: Settings
) -> None:
    job = jobs.load_job(command.analysis_id)
    if job is None or not job.config.critic.enabled:
        return
    if settings.critic_backend == "none":
        return
    _send(
        build_stage_command(
            analysis_id=command.analysis_id,
            stage_name="critic",
            configuration_hash=job.record.configuration_hash,
            pipeline_version=job.record.pipeline_version,
            trace_id=command.trace_id,
        )
    )


def _send(command: StageCommand, *, countdown: float | None = None) -> None:
    if _enqueue is not None:
        _enqueue(command, countdown)
        return
    from cine_analyzer.worker.enqueue import enqueue_command

    enqueue_command(command, countdown=countdown, settings=_settings)


def _canceled(request_id: str, stage: str) -> IngestError:
    from cine_analyzer.application.errors import ingest_error

    return ingest_error(
        "CANCELED_BY_CLIENT",
        "the analysis was canceled",
        request_id=request_id,
        retryable=False,
        stage=stage,
    )


def _require_runtime() -> tuple[Settings, JobRepository, "WorkerServices"]:
    if _settings is not None and _jobs is not None and _services is not None:
        return _settings, _jobs, _services
    from cine_analyzer.adapters.persistence.postgres import PostgresJobRepository
    from cine_analyzer.settings import load_settings
    from cine_analyzer.worker.services import build_worker_services

    settings = load_settings() if _settings is None else _settings
    if settings.database_url is None:
        message = "CINE_DATABASE_URL is required for Celery workers"
        raise RuntimeError(message)
    jobs = PostgresJobRepository(settings.database_url) if _jobs is None else _jobs
    services = build_worker_services(settings, jobs) if _services is None else _services
    bind_runtime(jobs=jobs, services=services, settings=settings, enqueue=_enqueue)
    return settings, jobs, services
