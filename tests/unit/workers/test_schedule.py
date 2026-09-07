"""DAG scheduling reads PostgreSQL stage rows, not Redis results."""

from uuid import uuid4

from tests.factories import ANALYSIS_ID

from cine_analyzer.domain.jobs import StageState
from cine_analyzer.ports.control import StageRunRecord
from cine_analyzer.worker.schedule import latest_by_stage, next_runnable_stage


def _run(stage: str, state: StageState, *, attempt: int = 1) -> StageRunRecord:
    return StageRunRecord(
        stage_run_id=uuid4(),
        analysis_id=ANALYSIS_ID,
        stage_name=stage,
        attempt=attempt,
        state=state,
        lease_token=None,
        worker_id=None,
        lease_expires_at=None,
        error_code=None,
        error_message=None,
    )


def test_empty_runs_start_at_sampling() -> None:
    assert next_runnable_stage(()) == "sampling"
    assert latest_by_stage(()) == {}


def test_succeeded_sampling_advances_to_report() -> None:
    runs = (_run("sampling", StageState.SUCCEEDED),)
    assert next_runnable_stage(runs) == "report"


def test_aggregate_waits_until_report_succeeded() -> None:
    runs = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.RUNNING),
    )
    assert next_runnable_stage(runs) is None
    ready = (
        _run("sampling", StageState.SUCCEEDED),
        _run("report", StageState.SUCCEEDED),
    )
    assert next_runnable_stage(ready) == "aggregate"
    done = (*ready, _run("aggregate", StageState.SUCCEEDED))
    assert next_runnable_stage(done) is None


def test_retryable_pending_skipped_and_in_flight() -> None:
    assert next_runnable_stage((_run("sampling", StageState.PENDING),)) == "sampling"
    assert next_runnable_stage((_run("sampling", StageState.FAILED_RETRYABLE),)) == "sampling"
    assert next_runnable_stage((_run("sampling", StageState.LEASED),)) is None
    skipped = (
        _run("sampling", StageState.SKIPPED),
        _run("report", StageState.PENDING),
    )
    assert next_runnable_stage(skipped) == "report"


def test_terminal_failure_stops_the_dag() -> None:
    assert next_runnable_stage((_run("sampling", StageState.FAILED_TERMINAL),)) is None
    higher = (
        _run("sampling", StageState.FAILED_RETRYABLE, attempt=1),
        _run("sampling", StageState.PENDING, attempt=2),
    )
    assert latest_by_stage(higher)["sampling"].attempt == 2
    assert next_runnable_stage(higher) == "sampling"
    older_second = (
        _run("sampling", StageState.PENDING, attempt=2),
        _run("sampling", StageState.FAILED_RETRYABLE, attempt=1),
    )
    assert latest_by_stage(older_second)["sampling"].attempt == 2
