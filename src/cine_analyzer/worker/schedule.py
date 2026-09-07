"""Schedule the next pipeline stage from PostgreSQL attempt rows, not Redis results."""

from cine_analyzer.domain.jobs import StageState
from cine_analyzer.ports.control import PIPELINE_STAGES, StageRunRecord

__all__ = ["latest_by_stage", "next_runnable_stage"]


def latest_by_stage(runs: tuple[StageRunRecord, ...]) -> dict[str, StageRunRecord]:
    """Highest attempt per stage name."""
    latest: dict[str, StageRunRecord] = {}
    for run in runs:
        previous = latest.get(run.stage_name)
        if previous is None or run.attempt > previous.attempt:
            latest[run.stage_name] = run
    return latest


def next_runnable_stage(runs: tuple[StageRunRecord, ...]) -> str | None:
    """First pipeline stage that is missing, pending, or retryable.

    In-flight leases and terminal failures stop the DAG. Aggregation is only
    returned after sampling and report have succeeded in PostgreSQL.
    """
    latest = latest_by_stage(runs)
    for name in PIPELINE_STAGES:
        run = latest.get(name)
        if run is None:
            return name
        if run.state in {StageState.SUCCEEDED, StageState.SKIPPED}:
            continue
        if run.state in {StageState.PENDING, StageState.FAILED_RETRYABLE}:
            return name
        return None
    return None
