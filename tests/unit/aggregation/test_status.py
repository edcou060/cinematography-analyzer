"""Status mapping and timeline windowing."""

from uuid import uuid4

from tests.factories import ANALYSIS_ID, DIGEST, VIDEO_ID, make_availability
from tests.unit.domain.test_timeline import _point

from cine_analyzer.application.status import build_status
from cine_analyzer.application.timeline_window import MAX_TIMELINE_POINTS, window_timeline
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState, StageState
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import SCHEMA_VERSION
from cine_analyzer.ports.control import AnalysisJob, StageRunRecord
from cine_analyzer.ports.ingestion import AnalysisRecord


def _job(*, state: AnalysisState = AnalysisState.RUNNING, progress: float = 0.0) -> AnalysisJob:
    return AnalysisJob(
        record=AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="e" * 64,
            state=state,
        ),
        progress=progress,
        config=AnalysisConfig(),
        failure_code="RESOURCE_STATE" if state is AnalysisState.FAILED else None,
        failure_message="aggregate failed" if state is AnalysisState.FAILED else None,
        report_artifact_id=None,
        timeline_artifact_id=None,
    )


def _run(name: str, state: StageState) -> StageRunRecord:
    return StageRunRecord(
        stage_run_id=uuid4(),
        analysis_id=ANALYSIS_ID,
        stage_name=name,
        attempt=1,
        state=state,
        lease_token=None,
        worker_id=None,
        lease_expires_at=None,
        error_code=None,
        error_message=None,
    )


def test_status_progress_comes_from_stage_weights_while_running() -> None:
    status = build_status(
        _job(),
        (_run("sampling", StageState.SUCCEEDED), _run("report", StageState.RUNNING)),
        request_id="req-1",
    )
    assert status.progress == 0.4
    assert status.completed_stages == ("sampling",)
    assert status.active_stages == ("report",)
    assert status.error is None


def test_status_includes_safe_error_on_terminal_failure() -> None:
    status = build_status(
        _job(state=AnalysisState.FAILED, progress=0.4),
        (_run("sampling", StageState.SUCCEEDED),),
        request_id="req-2",
    )
    assert status.error is not None
    assert status.error.code == "RESOURCE_STATE"
    assert status.progress == 0.4


def test_status_fills_unavailable_from_availability() -> None:
    status = build_status(
        _job(state=AnalysisState.PARTIAL, progress=1.0),
        (_run("sampling", StageState.SUCCEEDED), _run("report", StageState.SUCCEEDED)),
        availability=make_availability(),
        request_id="req-3",
    )
    assert "spatial" in status.unavailable_stages


def test_window_returns_points_inside_the_half_open_range() -> None:
    timeline = Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(_point(0), _point(1000), _point(2000), _point(3000)),
    )
    selected = window_timeline(timeline, start_ms=1000, end_ms=3000, max_points=10)
    assert [point.at_ms for point in selected] == [1000, 2000]


def test_window_downsamples_evenly_when_over_the_cap() -> None:
    points = tuple(_point(index * 10) for index in range(20))
    timeline = Timeline(schema_version=SCHEMA_VERSION, analysis_id=ANALYSIS_ID, points=points)
    selected = window_timeline(timeline, start_ms=0, end_ms=10_000, max_points=5)
    assert len(selected) == 5
    assert selected[0].at_ms == 0
    assert selected[-1].at_ms == 190


def test_window_cap_one_returns_the_first_point() -> None:
    timeline = Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(_point(0), _point(1000), _point(2000)),
    )
    selected = window_timeline(timeline, start_ms=0, end_ms=5000, max_points=1)
    assert selected == (_point(0),)


def test_status_keeps_explicit_unavailable_names() -> None:
    status = build_status(
        _job(state=AnalysisState.PARTIAL, progress=1.0),
        (),
        unavailable_stages=("audio",),
        availability=make_availability(),
        request_id="req-4",
    )
    assert status.unavailable_stages == ("audio",)


def test_window_empty_range_returns_no_points() -> None:
    timeline = Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(_point(0), _point(1000)),
    )
    assert window_timeline(timeline, start_ms=5000, end_ms=6000, max_points=10) == ()


def test_window_respects_the_global_cap() -> None:
    assert MAX_TIMELINE_POINTS == 2000
    timeline = Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(_point(0), _point(1000)),
    )
    selected = window_timeline(timeline, start_ms=0, end_ms=5000, max_points=50_000)
    assert len(selected) == 2
