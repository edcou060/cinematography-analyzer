"""API backpressure for new analysis identities."""

from cine_analyzer.application.errors import ingest_error
from cine_analyzer.application.identity import make_analysis_key
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.ports.control import JobRepository
from cine_analyzer.ports.ingestion import VideoRecord
from cine_analyzer.settings import Settings

__all__ = ["enforce_inflight_quota"]


def enforce_inflight_quota(
    jobs: JobRepository,
    settings: Settings,
    *,
    video: VideoRecord,
    config: AnalysisConfig,
    request_id: str,
) -> None:
    """Refuse a new analysis when non-terminal rows already fill the cap.

    Reuse of an existing identity is allowed so clients can poll a running job.
    """
    analysis_key = make_analysis_key(
        video_sha256=video.metadata.content_sha256,
        config=config,
    )
    if jobs.get_analysis_by_key(analysis_key) is not None:
        return
    if jobs.count_inflight() < settings.max_inflight_analyses:
        return
    raise ingest_error(
        "RESOURCE_LIMIT",
        "in-flight analysis quota reached",
        request_id=request_id,
        retryable=True,
        stage="control",
    )
