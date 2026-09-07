"""Build AnalysisStatusResponse from authoritative rows."""

from cine_analyzer.application.aggregation import progress_from_stages, unavailable_pillars
from cine_analyzer.domain.errors import SafeError
from cine_analyzer.domain.jobs import AnalysisStatusResponse, StageState, analysis_is_terminal
from cine_analyzer.domain.report import ReportAvailability
from cine_analyzer.ports.control import STAGE_PROGRESS_WEIGHTS, AnalysisJob, StageRunRecord

__all__ = ["build_status"]


def build_status(
    job: AnalysisJob,
    runs: tuple[StageRunRecord, ...],
    *,
    unavailable_stages: tuple[str, ...] = (),
    availability: ReportAvailability | None = None,
    request_id: str,
) -> AnalysisStatusResponse:
    """Progress and stage lists. Terminal failures include a SafeError when recorded."""
    if not unavailable_stages and availability is not None:
        unavailable_stages = unavailable_pillars(availability)
    completed = tuple(
        name
        for name in STAGE_PROGRESS_WEIGHTS
        if any(
            run.stage_name == name and run.state in {StageState.SUCCEEDED, StageState.SKIPPED}
            for run in runs
        )
    )
    active = tuple(
        dict.fromkeys(
            run.stage_name for run in runs if run.state in {StageState.LEASED, StageState.RUNNING}
        )
    )
    error: SafeError | None = None
    if analysis_is_terminal(job.record.state) and job.failure_code and job.failure_message:
        error = SafeError(
            code=job.failure_code,
            message=job.failure_message,
            retryable=False,
            stage="aggregate",
            request_id=request_id,
        )
    return AnalysisStatusResponse(
        analysis_id=job.record.analysis_id,
        state=job.record.state,
        progress=progress_from_stages(runs)
        if not analysis_is_terminal(job.record.state)
        else job.progress,
        completed_stages=completed,
        active_stages=active,
        unavailable_stages=unavailable_stages,
        error=error,
    )
