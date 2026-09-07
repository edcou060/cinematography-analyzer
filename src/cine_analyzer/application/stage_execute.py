"""Lease, run, and complete one named pipeline stage.

Local poll and Celery tasks share this path so only submission differs (ADR-0002).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter
from uuid import UUID

from cine_analyzer.application.errors import IngestError
from cine_analyzer.domain.jobs import AnalysisState, StageState
from cine_analyzer.observability.metrics import error_class_for, incr, observe
from cine_analyzer.ports.control import JobRepository

__all__ = [
    "StageOutcome",
    "honor_cancel",
    "run_leased_stage",
    "should_cancel",
    "tick_cancel",
]


class StageOutcome(StrEnum):
    """How a leased attempt ended. Retryable failures still raise ``IngestError``."""

    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    CANCELED = "canceled"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"


def should_cancel(jobs: JobRepository, analysis_id: UUID) -> bool:
    """True when the analysis row is ``CANCEL_REQUESTED``."""
    job = jobs.load_job(analysis_id)
    return job is not None and job.record.state is AnalysisState.CANCEL_REQUESTED


def tick_cancel(cancel_check: Callable[[], None] | None) -> None:
    """Run a cooperative cancel hook between shots, batches, or windows."""
    if cancel_check is not None:
        cancel_check()


def honor_cancel(jobs: JobRepository, analysis_id: UUID) -> None:
    """Cancel in-flight attempts and move the analysis to ``CANCELED``."""
    for run in jobs.list_stage_runs(analysis_id):
        if run.state in {StageState.PENDING, StageState.LEASED, StageState.RUNNING}:
            jobs.cancel_stage(analysis_id, run.stage_name, run.attempt)
    job = jobs.load_job(analysis_id)
    if job is not None and job.record.state is AnalysisState.RUNNING:
        jobs.set_analysis_state(
            analysis_id,
            expected=AnalysisState.RUNNING,
            target=AnalysisState.CANCEL_REQUESTED,
        )
    jobs.set_analysis_state(
        analysis_id,
        expected=AnalysisState.CANCEL_REQUESTED,
        target=AnalysisState.CANCELED,
    )


def run_leased_stage(
    jobs: JobRepository,
    analysis_id: UUID,
    stage_name: str,
    *,
    worker_id: str,
    ttl_ms: int,
    now: datetime,
    work: Callable[[], object],
    max_attempts: int = 3,
) -> StageOutcome:
    """Acquire, run, and complete a stage. Retryable errors are recorded then raised."""
    started = perf_counter()
    outcome = StageOutcome.FAILED
    error_class = "none"
    try:
        outcome = _run_leased_stage(
            jobs,
            analysis_id,
            stage_name,
            worker_id=worker_id,
            ttl_ms=ttl_ms,
            now=now,
            work=work,
            max_attempts=max_attempts,
        )
        return outcome
    except IngestError as error:
        error_class = error_class_for(error.safe.code)
        raise
    finally:
        duration_ms = max(0, int((perf_counter() - started) * 1000))
        observe("stage_duration_ms", duration_ms, stage=stage_name)
        incr(
            "stage_runs_total",
            stage=stage_name,
            state=outcome.value,
            error_class=error_class,
        )


def _run_leased_stage(
    jobs: JobRepository,
    analysis_id: UUID,
    stage_name: str,
    *,
    worker_id: str,
    ttl_ms: int,
    now: datetime,
    work: Callable[[], object],
    max_attempts: int = 3,
) -> StageOutcome:
    if should_cancel(jobs, analysis_id):
        honor_cancel(jobs, analysis_id)
        return StageOutcome.CANCELED
    latest = [run for run in jobs.list_stage_runs(analysis_id) if run.stage_name == stage_name]
    if latest and max(latest, key=lambda run: run.attempt).state is StageState.SUCCEEDED:
        return StageOutcome.SKIPPED
    lease = jobs.acquire_stage(
        analysis_id,
        stage_name,
        worker_id=worker_id,
        ttl_ms=ttl_ms,
        now=now,
    )
    if lease is None:
        jobs.set_analysis_state(
            analysis_id,
            expected=AnalysisState.RUNNING,
            target=AnalysisState.FAILED,
            failure_code="RESOURCE_STATE",
            failure_message="a stage lease could not be acquired",
        )
        return StageOutcome.LEASE_LOST
    if not jobs.start_stage(lease, now=now):
        return StageOutcome.LEASE_LOST
    try:
        work()
        jobs.heartbeat_stage(lease, ttl_ms=ttl_ms, now=datetime.now(tz=UTC))
        if jobs.complete_stage(lease, now=datetime.now(tz=UTC)):
            return StageOutcome.SUCCEEDED
        return StageOutcome.LEASE_LOST
    except IngestError as error:
        if error.safe.code.startswith("CANCELED_"):
            honor_cancel(jobs, analysis_id)
            return StageOutcome.CANCELED
        attempt = lease.attempt
        cap_hit = attempt >= max_attempts
        terminal = (not error.safe.retryable) or cap_hit
        jobs.fail_stage(
            lease,
            terminal=terminal,
            code=error.safe.code,
            message=error.safe.message,
            now=datetime.now(tz=UTC),
        )
        if not terminal:
            jobs.insert_retry_attempt(analysis_id, stage_name)
        if terminal and error.safe.retryable:
            jobs.set_analysis_state(
                analysis_id,
                expected=AnalysisState.RUNNING,
                target=AnalysisState.FAILED,
                failure_code=error.safe.code,
                failure_message=error.safe.message,
            )
        raise
