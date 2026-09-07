"""Local worker: claim queued analyses, lease stages, run existing pipeline entry points."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TextIO
from uuid import UUID, uuid4

from pydantic import ValidationError

from cine_analyzer.adapters.persistence.postgres import PostgresJobRepository
from cine_analyzer.application.aggregation import persist_report_outcome
from cine_analyzer.application.errors import IngestError, ingest_error
from cine_analyzer.application.stage_execute import (
    StageOutcome,
    honor_cancel,
    run_leased_stage,
    should_cancel,
)
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.logging_setup import bind_context, configure_logging, get_logger
from cine_analyzer.ports.control import JobRepository
from cine_analyzer.ports.ingestion import AnalysisRecord
from cine_analyzer.settings import Settings, load_settings
from cine_analyzer.worker.services import WorkerServices, build_worker_services

__all__ = ["process_once", "run_worker"]

EXIT_OK = 0
EXIT_FAILED = 1


def run_worker(
    *,
    once: bool,
    stdout: TextIO,
    stderr: TextIO,
    jobs: JobRepository | None = None,
    services: WorkerServices | None = None,
    max_loops: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Poll PostgreSQL for queued work. ``once`` processes at most one claim attempt."""
    try:
        settings = load_settings()
    except ValidationError as error:
        stderr.write(f"settings are invalid; the worker was not started\n{error}\n")
        return EXIT_FAILED
    if settings.execution_backend == "celery":
        stderr.write(
            "CINE_EXECUTION_BACKEND=celery requires cine-analyzer celery-worker, "
            "not the local poll worker\n"
        )
        return EXIT_FAILED
    configure_logging(settings, stream=stderr)
    owns = False
    repository = jobs
    if repository is None:
        if settings.database_url is None:
            stderr.write("CINE_DATABASE_URL is required to run the worker\n")
            return EXIT_FAILED
        repository = PostgresJobRepository(settings.database_url)
        owns = True
    bound_services = (
        services if services is not None else build_worker_services(settings, repository)
    )
    loops = 0
    try:
        while True:
            processed = process_once(
                jobs=repository,
                services=bound_services,
                settings=settings,
            )
            loops += 1
            if processed:
                stdout.write("processed\n")
            else:
                stdout.write("idle\n")
            if once:
                return EXIT_OK
            if max_loops is not None and loops >= max_loops:
                return EXIT_OK
            if not processed:
                sleep(settings.worker_poll_ms / 1000)
    finally:
        if owns:
            repository.close()


def process_once(
    *,
    jobs: JobRepository,
    services: WorkerServices,
    settings: Settings,
    now: datetime | None = None,
    request_id: str | None = None,
) -> bool:
    """Claim one analysis if available and run leased stages. False when idle."""
    moment = datetime.now(tz=UTC) if now is None else now
    worker_id = settings.worker_id
    claimed = jobs.claim_queued(worker_id=worker_id, now=moment)
    if claimed is None:
        return False
    rid = uuid4().hex if request_id is None else request_id
    get_logger(__name__).info(
        "worker.claimed",
        analysis_id=str(claimed.analysis_id),
        state=claimed.state.value,
        worker_id=worker_id,
    )
    with bind_context(
        request_id=rid,
        trace_id=rid,
        analysis_id=str(claimed.analysis_id),
        video_id=str(claimed.video_id),
        worker_id=worker_id,
    ):
        return _process_claimed(
            claimed=claimed,
            jobs=jobs,
            services=services,
            settings=settings,
            moment=moment,
            rid=rid,
        )


def _process_claimed(
    *,
    claimed: AnalysisRecord,
    jobs: JobRepository,
    services: WorkerServices,
    settings: Settings,
    moment: datetime,
    rid: str,
) -> bool:
    worker_id = settings.worker_id
    if claimed.state is AnalysisState.CANCEL_REQUESTED:
        honor_cancel(jobs, claimed.analysis_id)
        return True
    job = jobs.load_job(claimed.analysis_id)
    video = jobs.get_video(claimed.video_id)
    if job is None or video is None:
        jobs.set_analysis_state(
            claimed.analysis_id,
            expected=AnalysisState.RUNNING,
            target=AnalysisState.FAILED,
            failure_code="ARTIFACT_MISSING",
            failure_message="the analysis inputs could not be loaded",
        )
        return True

    def cancel_check() -> None:
        if should_cancel(jobs, claimed.analysis_id):
            raise ingest_error(
                "CANCELED_BY_CLIENT",
                "the analysis was canceled",
                request_id=rid,
                retryable=False,
                stage="worker",
            )

    try:
        if not _run_named_stage(
            jobs,
            claimed.analysis_id,
            "sampling",
            worker_id=worker_id,
            ttl_ms=settings.lease_ttl_ms,
            now=moment,
            max_attempts=settings.stage_retry_max_attempts,
            work=lambda: services.sampling.execute(
                video=video,
                analysis=job.record,
                config=job.config,
                request_id=rid,
                cancel_check=cancel_check,
            ),
        ):
            return True
        moment = datetime.now(tz=UTC)
        if should_cancel(jobs, claimed.analysis_id):
            honor_cancel(jobs, claimed.analysis_id)
            return True
        if not _run_named_stage(
            jobs,
            claimed.analysis_id,
            "report",
            worker_id=worker_id,
            ttl_ms=settings.lease_ttl_ms,
            now=moment,
            max_attempts=settings.stage_retry_max_attempts,
            work=lambda: services.report.execute(
                video=video,
                analysis=job.record,
                config=job.config,
                request_id=rid,
                cancel_check=cancel_check,
            ),
        ):
            return True
        moment = datetime.now(tz=UTC)
        if should_cancel(jobs, claimed.analysis_id):
            honor_cancel(jobs, claimed.analysis_id)
            return True
        _run_named_stage(
            jobs,
            claimed.analysis_id,
            "aggregate",
            worker_id=worker_id,
            ttl_ms=settings.lease_ttl_ms,
            now=moment,
            max_attempts=settings.stage_retry_max_attempts,
            work=lambda: persist_report_outcome(jobs, services.store, claimed.analysis_id),
        )
        from cine_analyzer.application.critic import persist_critique_for_job

        persist_critique_for_job(jobs, services.store, claimed.analysis_id, settings)
    except IngestError as error:
        jobs.set_analysis_state(
            claimed.analysis_id,
            expected=AnalysisState.RUNNING,
            target=AnalysisState.FAILED,
            failure_code=error.safe.code,
            failure_message=error.safe.message,
        )
    return True


def _run_named_stage(
    jobs: JobRepository,
    analysis_id: UUID,
    stage_name: str,
    *,
    worker_id: str,
    ttl_ms: int,
    now: datetime,
    work: Callable[[], object],
    max_attempts: int = 3,
) -> bool:
    """Acquire, run, and complete a stage. False if cancelled, failed, or lease lost."""
    outcome = run_leased_stage(
        jobs,
        analysis_id,
        stage_name,
        worker_id=worker_id,
        ttl_ms=ttl_ms,
        now=now,
        work=work,
        max_attempts=max_attempts,
    )
    return outcome in {StageOutcome.SUCCEEDED, StageOutcome.SKIPPED}
