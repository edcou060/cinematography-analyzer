"""Decide analysis terminal state from stage outcomes and report availability."""

from uuid import UUID

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.jobs import AnalysisState, StageState, is_partial_outcome
from cine_analyzer.domain.report import AnalysisReport, ReportAvailability, StageAvailability
from cine_analyzer.ports.control import (
    PIPELINE_STAGES,
    STAGE_PROGRESS_WEIGHTS,
    JobRepository,
    ReportSummaryRecord,
    ShotIntervalRecord,
    StageRunRecord,
)
from cine_analyzer.ports.ingestion import ArtifactStore

__all__ = [
    "OPTIONAL_PILLARS",
    "REQUIRED_STAGES",
    "decide_analysis_outcome",
    "persist_report_outcome",
    "progress_from_stages",
    "unavailable_pillars",
]

REQUIRED_STAGES: frozenset[str] = frozenset({"sampling", "report"})
OPTIONAL_PILLARS: tuple[str, ...] = (
    "chromatic",
    "spatial",
    "motion",
    "audio",
    "tension",
)


def progress_from_stages(runs: tuple[StageRunRecord, ...]) -> float:
    """Sum configured weights for succeeded or skipped stage names."""
    done: set[str] = set()
    for run in runs:
        if run.state in {StageState.SUCCEEDED, StageState.SKIPPED}:
            done.add(run.stage_name)
    total = sum(STAGE_PROGRESS_WEIGHTS[name] for name in PIPELINE_STAGES if name in done)
    return min(1.0, max(0.0, total))


def unavailable_pillars(availability: ReportAvailability) -> tuple[str, ...]:
    """Names whose availability is not COMPLETE."""
    mapping = {
        "chromatic": availability.chromatic,
        "spatial": availability.spatial,
        "motion": availability.motion,
        "audio": availability.audio,
        "tension": availability.tension,
        "critic": availability.critic,
    }
    return tuple(
        name for name, status in mapping.items() if status is not StageAvailability.COMPLETE
    )


def decide_analysis_outcome(
    runs: tuple[StageRunRecord, ...],
    availability: ReportAvailability | None,
    *,
    has_audio: bool,
    spatial_requested: bool,
) -> AnalysisState:
    """FAILED, PARTIAL, or SUCCEEDED. Cancel is handled by the worker, not here."""
    latest = _latest_by_stage(runs)
    for name in REQUIRED_STAGES:
        run = latest.get(name)
        if run is None or run.state is StageState.FAILED_TERMINAL:
            return AnalysisState.FAILED
        if run.state is not StageState.SUCCEEDED:
            return AnalysisState.FAILED
    if availability is None:
        return AnalysisState.FAILED
    optional_failed = _optional_pillar_failed(
        availability, has_audio=has_audio, spatial_requested=spatial_requested
    )
    if is_partial_outcome(
        required_dependencies_terminal=True,
        optional_stage_failed=optional_failed,
    ):
        return AnalysisState.PARTIAL
    return AnalysisState.SUCCEEDED


def _latest_by_stage(runs: tuple[StageRunRecord, ...]) -> dict[str, StageRunRecord]:
    latest: dict[str, StageRunRecord] = {}
    for run in runs:
        previous = latest.get(run.stage_name)
        if previous is None or run.attempt > previous.attempt:
            latest[run.stage_name] = run
    return latest


def _optional_pillar_failed(
    availability: ReportAvailability,
    *,
    has_audio: bool,
    spatial_requested: bool,
) -> bool:
    if availability.chromatic in {StageAvailability.UNAVAILABLE, StageAvailability.PARTIAL}:
        return True
    if spatial_requested and availability.spatial is not StageAvailability.COMPLETE:
        return True
    if availability.motion in {StageAvailability.UNAVAILABLE, StageAvailability.PARTIAL}:
        return True
    if has_audio and availability.audio is not StageAvailability.COMPLETE:
        return True
    return availability.tension is StageAvailability.UNAVAILABLE


def persist_report_outcome(
    jobs: JobRepository,
    store: ArtifactStore,
    analysis_id: UUID,
    *,
    expected: AnalysisState = AnalysisState.RUNNING,
) -> AnalysisState:
    """Load the report artifact, persist summary/shots, and CAS the analysis terminal state."""
    job = jobs.load_job(analysis_id)
    if job is None:
        jobs.set_analysis_state(
            analysis_id,
            expected=expected,
            target=AnalysisState.FAILED,
            progress=progress_from_stages(jobs.list_stage_runs(analysis_id)),
            failure_code="ARTIFACT_MISSING",
            failure_message="the analysis could not be loaded for aggregation",
        )
        return AnalysisState.FAILED
    video = jobs.get_video(job.record.video_id)
    report_row = jobs.get_artifact_by_storage_key(f"analyses/{analysis_id.hex}/report.json")
    if video is None or report_row is None:
        jobs.set_analysis_state(
            analysis_id,
            expected=expected,
            target=AnalysisState.FAILED,
            progress=progress_from_stages(jobs.list_stage_runs(analysis_id)),
            failure_code="ARTIFACT_MISSING",
            failure_message="the report artifact is not available",
        )
        return AnalysisState.FAILED
    try:
        payload = store.local_path(report_row.storage_key).read_bytes()
        report = AnalysisReport.model_validate_json(payload)
    except (AdapterError, OSError, ValueError):
        jobs.set_analysis_state(
            analysis_id,
            expected=expected,
            target=AnalysisState.FAILED,
            progress=progress_from_stages(jobs.list_stage_runs(analysis_id)),
            failure_code="SCHEMA_INVALID",
            failure_message="the report artifact could not be read",
        )
        return AnalysisState.FAILED
    timeline_row = jobs.get_artifact_by_storage_key(f"analyses/{analysis_id.hex}/timeline.json")
    timeline_id = None if timeline_row is None else timeline_row.artifact_id
    jobs.save_shots(
        analysis_id,
        tuple(
            ShotIntervalRecord(
                shot_id=item.shot.shot_id,
                analysis_id=analysis_id,
                shot_index=item.shot.index,
                start_ms=item.shot.time_range.start_ms,
                end_ms=item.shot.time_range.end_ms,
            )
            for item in report.shots
        ),
    )
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=analysis_id,
            summary=report.summary,
            availability=report.availability,
            report_artifact_id=report_row.artifact_id,
            timeline_artifact_id=timeline_id,
        )
    )
    jobs.link_artifact(report_row.artifact_id, analysis_id=analysis_id)
    if timeline_row is not None:
        jobs.link_artifact(timeline_row.artifact_id, analysis_id=analysis_id)
    outcome = decide_analysis_outcome(
        jobs.list_stage_runs(analysis_id),
        report.availability,
        has_audio=video.metadata.has_audio,
        spatial_requested=job.config.spatial.backend != "none",
    )
    jobs.set_analysis_state(
        analysis_id,
        expected=expected,
        target=outcome,
        progress=1.0,
        report_artifact_id=report_row.artifact_id,
        timeline_artifact_id=timeline_id,
    )
    return outcome
