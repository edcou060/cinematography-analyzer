"""HTTP routes. Heavy analysis is never invoked here."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from cine_analyzer.api.deps import (
    analyze_of,
    ingest_of,
    jobs_of,
    request_id_of,
    settings_of,
    store_of,
)
from cine_analyzer.api.errors import (
    ingest_to_api,
    not_found_artifact,
    not_found_video,
    not_ready,
    schema_invalid,
)
from cine_analyzer.api.schemas import (
    AnalysisAccepted,
    AnalysisCreateRequest,
    HealthResponse,
    TimelineWindowResponse,
    VideoAccepted,
)
from cine_analyzer.application.errors import AdapterError, IngestError, ingest_error
from cine_analyzer.application.quota import enforce_inflight_quota
from cine_analyzer.application.readiness import ping_broker
from cine_analyzer.application.status import build_status
from cine_analyzer.application.timeline_window import MAX_TIMELINE_POINTS, window_timeline
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import AnalysisReport, Critique, ShotAnalysis
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.observability.metrics import MetricsSnapshot, incr, snapshot
from cine_analyzer.worker.enqueue import maybe_enqueue_analysis

health_router = APIRouter(tags=["health"])
videos_router = APIRouter(prefix="/v1", tags=["videos"])
analyses_router = APIRouter(prefix="/v1", tags=["analyses"])
artifacts_router = APIRouter(prefix="/v1", tags=["artifacts"])


@health_router.get("/health/live", response_model=HealthResponse)
def live() -> HealthResponse:
    """Process liveness. Does not check PostgreSQL."""
    return HealthResponse(status="ok")


@health_router.get("/health/ready", response_model=HealthResponse)
def ready(request: Request) -> HealthResponse | JSONResponse:
    """Fail when the database (and Celery broker, when configured) cannot be reached."""
    jobs = getattr(request.app.state, "jobs", None)
    if jobs is None:
        return JSONResponse(
            content=HealthResponse(status="unavailable").model_dump(mode="json"),
            status_code=503,
        )
    try:
        jobs.ping()
        settings = getattr(request.app.state, "settings", None)
        if (
            settings is not None
            and settings.execution_backend == "celery"
            and settings.redis_url is not None
        ):
            ping_broker(settings.redis_url)
    except AdapterError:
        return JSONResponse(
            content=HealthResponse(status="unavailable").model_dump(mode="json"),
            status_code=503,
        )
    return HealthResponse(status="ok")


@health_router.get("/metrics", response_model=MetricsSnapshot)
def metrics(request: Request) -> MetricsSnapshot:
    """In-process counters and histograms. IDs are not labels."""
    jobs = getattr(request.app.state, "jobs", None)
    active = 0
    if jobs is not None:
        try:
            active = jobs.count_inflight()
        except AdapterError:
            active = 0
    return snapshot(active_jobs=active)


@videos_router.post("/videos", response_model=VideoAccepted, status_code=201)
async def upload_video(request: Request, file: UploadFile) -> VideoAccepted:
    """Stream an upload into the Phase 03 ingest use case."""
    ingest = ingest_of(request)
    settings = settings_of(request)
    request_id = request_id_of(request)
    filename = file.filename or "upload.bin"
    quarantine = settings.artifact_root / "quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    destination = quarantine / uuid4().hex
    config = AnalysisConfig()
    try:
        await _stream_upload(
            file,
            destination,
            chunk_bytes=settings.ingest_chunk_bytes,
            max_bytes=config.limits.max_upload_bytes,
            request_id=request_id,
        )
        result = ingest.execute(
            destination,
            original_filename=filename,
            config=config,
            request_id=request_id,
        )
    except IngestError as error:
        incr("upload_rejections_total", reason=error.safe.code)
        raise ingest_to_api(error) from error
    finally:
        destination.unlink(missing_ok=True)
        await file.close()
    meta = result.video.metadata
    return VideoAccepted(
        video_id=meta.video_id,
        content_sha256=meta.content_sha256,
        reused=result.reused,
        duration_ms=meta.duration_ms,
        width=meta.width,
        height=meta.height,
        has_audio=meta.has_audio,
    )


@analyses_router.post("/analyses", response_model=AnalysisAccepted, status_code=202)
def create_analysis(request: Request, body: AnalysisCreateRequest) -> JSONResponse:
    """Queue an analysis. Video identity stays separate from config identity."""
    jobs = jobs_of(request)
    analyze = analyze_of(request)
    request_id = request_id_of(request)
    video = jobs.get_video(body.video_id)
    if video is None:
        raise not_found_video(request)
    config = AnalysisConfig() if body.config is None else body.config
    try:
        enforce_inflight_quota(
            jobs,
            settings_of(request),
            video=video,
            config=config,
            request_id=request_id,
        )
        created = analyze.execute(video=video, config=config, request_id=request_id)
    except IngestError as error:
        raise ingest_to_api(error) from error
    incr("analysis_jobs_total", state=created.analysis.state.value)
    jobs.record_config(created.analysis.analysis_id, config)
    jobs.ensure_pending_stages(created.analysis.analysis_id)
    maybe_enqueue_analysis(
        created.analysis.analysis_id,
        state=created.analysis.state,
        reused=created.reused,
        settings=settings_of(request),
        trace_id=request_id,
        configuration_hash=created.configuration_hash,
        pipeline_version=created.analysis.pipeline_version,
    )
    payload = AnalysisAccepted(
        analysis_id=created.analysis.analysis_id,
        video_id=created.analysis.video_id,
        configuration_hash=created.configuration_hash,
        pipeline_version=created.analysis.pipeline_version,
        reused=created.reused,
        state=created.analysis.state,
    )
    return JSONResponse(content=payload.model_dump(mode="json"), status_code=202)


@analyses_router.get("/analyses/{analysis_id}")
def get_analysis(request: Request, analysis_id: UUID) -> JSONResponse:
    """Status, progress, and unavailable pillars."""
    jobs = jobs_of(request)
    request_id = request_id_of(request)
    job = jobs.load_job(analysis_id)
    if job is None:
        raise not_found_artifact(request)
    summary = jobs.get_report_summary(analysis_id)
    availability = None if summary is None else summary.availability
    status = build_status(
        job,
        jobs.list_stage_runs(analysis_id),
        availability=availability,
        request_id=request_id,
    )
    return JSONResponse(content=status.model_dump(mode="json"))


@analyses_router.post("/analyses/{analysis_id}/cancel")
def cancel_analysis(request: Request, analysis_id: UUID) -> JSONResponse:
    """Request cooperative cancellation."""
    jobs = jobs_of(request)
    request_id = request_id_of(request)
    updated = jobs.request_cancel(analysis_id, now=datetime.now(tz=UTC))
    if updated is None:
        raise not_found_artifact(request)
    job = jobs.load_job(analysis_id)
    if job is None:
        raise not_found_artifact(request)
    status = build_status(
        job,
        jobs.list_stage_runs(analysis_id),
        request_id=request_id,
    )
    return JSONResponse(content=status.model_dump(mode="json"))


@analyses_router.get("/analyses/{analysis_id}/report", response_model=AnalysisReport)
def get_report(request: Request, analysis_id: UUID) -> AnalysisReport:
    """Canonical AnalysisReport JSON once aggregation has finished."""
    jobs = jobs_of(request)
    store = store_of(request)
    job = jobs.load_job(analysis_id)
    if job is None:
        raise not_found_artifact(request)
    if job.record.state not in {AnalysisState.SUCCEEDED, AnalysisState.PARTIAL}:
        raise not_ready(request)
    summary = jobs.get_report_summary(analysis_id)
    if summary is None:
        raise not_ready(request)
    artifact = jobs.get_artifact(summary.report_artifact_id)
    if artifact is None:
        raise not_found_artifact(request)
    try:
        payload = store.local_path(artifact.storage_key).read_bytes()
        return AnalysisReport.model_validate_json(payload)
    except (AdapterError, OSError, ValueError) as error:
        raise not_found_artifact(request) from error


@analyses_router.get("/analyses/{analysis_id}/critique", response_model=Critique)
def get_critique(request: Request, analysis_id: UUID) -> Critique:
    """Stored interpretation. Omitted when the critic did not run."""
    jobs = jobs_of(request)
    job = jobs.load_job(analysis_id)
    if job is None:
        raise not_found_artifact(request)
    record = jobs.get_latest_critique(analysis_id)
    if record is None:
        return Critique(status=MetricStatus.NOT_COMPUTED)
    return record.critique


@analyses_router.get(
    "/analyses/{analysis_id}/timeline",
    response_model=TimelineWindowResponse,
)
def get_timeline(
    request: Request,
    analysis_id: UUID,
    start_ms: Annotated[int, Query(ge=0)],
    end_ms: Annotated[int, Query(ge=0)],
    max_points: Annotated[int, Query(ge=1, le=MAX_TIMELINE_POINTS)],
) -> TimelineWindowResponse:
    """Windowed, downsampled tension-proxy timeline."""
    if end_ms <= start_ms:
        raise schema_invalid(request, "end_ms must be greater than start_ms")
    jobs = jobs_of(request)
    store = store_of(request)
    job = jobs.load_job(analysis_id)
    if job is None:
        raise not_found_artifact(request)
    if job.record.state not in {AnalysisState.SUCCEEDED, AnalysisState.PARTIAL}:
        raise not_ready(request)
    summary = jobs.get_report_summary(analysis_id)
    if summary is None or summary.timeline_artifact_id is None:
        raise not_found_artifact(request)
    artifact = jobs.get_artifact(summary.timeline_artifact_id)
    if artifact is None:
        raise not_found_artifact(request)
    try:
        payload = store.local_path(artifact.storage_key).read_bytes()
        timeline = Timeline.model_validate_json(payload)
    except (AdapterError, OSError, ValueError) as error:
        raise not_found_artifact(request) from error
    points = window_timeline(timeline, start_ms=start_ms, end_ms=end_ms, max_points=max_points)
    return TimelineWindowResponse(
        analysis_id=analysis_id,
        start_ms=start_ms,
        end_ms=end_ms,
        max_points=max_points,
        points=points,
    )


@analyses_router.get(
    "/analyses/{analysis_id}/shots/{shot_id}",
    response_model=ShotAnalysis,
)
def get_shot(request: Request, analysis_id: UUID, shot_id: UUID) -> ShotAnalysis:
    """One shot's measured metrics from the canonical report."""
    jobs = jobs_of(request)
    store = store_of(request)
    interval = jobs.get_shot(analysis_id, shot_id)
    if interval is None:
        raise not_found_artifact(request)
    job = jobs.load_job(analysis_id)
    if job is None or job.record.state not in {AnalysisState.SUCCEEDED, AnalysisState.PARTIAL}:
        raise not_ready(request)
    summary = jobs.get_report_summary(analysis_id)
    if summary is None:
        raise not_ready(request)
    artifact = jobs.get_artifact(summary.report_artifact_id)
    if artifact is None:
        raise not_found_artifact(request)
    try:
        payload = store.local_path(artifact.storage_key).read_bytes()
        report = AnalysisReport.model_validate_json(payload)
    except (AdapterError, OSError, ValueError) as error:
        raise not_found_artifact(request) from error
    for item in report.shots:
        if item.shot.shot_id == shot_id:
            return item
    raise not_found_artifact(request)


@artifacts_router.get("/artifacts/{artifact_id}")
def get_artifact(request: Request, artifact_id: UUID) -> Response:
    """Authorized stream. Possession of the server-issued UUID is the capability."""
    jobs = jobs_of(request)
    store = store_of(request)
    record = jobs.get_artifact(artifact_id)
    if record is None:
        raise not_found_artifact(request)
    try:
        path: Path = store.local_path(record.storage_key)
    except AdapterError as error:
        raise not_found_artifact(request) from error
    return FileResponse(
        path=path,
        media_type=record.media_type,
        filename=None,
        content_disposition_type="inline",
    )


async def _stream_upload(
    upload: UploadFile,
    destination: Path,
    *,
    chunk_bytes: int,
    max_bytes: int,
    request_id: str,
) -> None:
    written = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(chunk_bytes)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise ingest_error(
                    "MEDIA_TOO_LARGE",
                    "upload exceeds the configured size limit",
                    request_id=request_id,
                    retryable=False,
                )
            handle.write(chunk)
