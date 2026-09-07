"""FastAPI dependencies. This module must not import CV or report-stage analyzers."""

from uuid import uuid4

from fastapi import Request

from cine_analyzer.api.errors import ApiError
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.ingest import IngestVideo
from cine_analyzer.domain.errors import SafeError
from cine_analyzer.ports.control import JobRepository
from cine_analyzer.ports.ingestion import ArtifactStore
from cine_analyzer.settings import Settings

__all__ = [
    "analyze_of",
    "ingest_of",
    "jobs_of",
    "request_id_of",
    "settings_of",
    "store_of",
]


def request_id_of(request: Request) -> str:
    """Return the middleware-assigned request id, or mint one."""
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    minted = uuid4().hex
    request.state.request_id = minted
    return minted


def settings_of(request: Request) -> Settings:
    """Deployment settings bound at process start."""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise ApiError(
            SafeError(
                code="RESOURCE_STATE",
                message="the control plane is not configured",
                retryable=True,
                stage="control",
                request_id=request_id_of(request),
            ),
            503,
        )
    return settings


def jobs_of(request: Request) -> JobRepository:
    """Authoritative PostgreSQL repository."""
    jobs = getattr(request.app.state, "jobs", None)
    if jobs is None:
        raise ApiError(
            SafeError(
                code="RESOURCE_STATE",
                message="the database is not configured",
                retryable=True,
                stage="control",
                request_id=request_id_of(request),
            ),
            503,
        )
    return jobs  # type: ignore[no-any-return]


def store_of(request: Request) -> ArtifactStore:
    """Filesystem artifact store."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise ApiError(
            SafeError(
                code="RESOURCE_STATE",
                message="the artifact store is not configured",
                retryable=True,
                stage="control",
                request_id=request_id_of(request),
            ),
            503,
        )
    return store  # type: ignore[no-any-return]


def ingest_of(request: Request) -> IngestVideo:
    """Phase 03 ingest use case."""
    ingest = getattr(request.app.state, "ingest", None)
    if ingest is None:
        raise ApiError(
            SafeError(
                code="RESOURCE_STATE",
                message="ingest is not configured",
                retryable=True,
                stage="control",
                request_id=request_id_of(request),
            ),
            503,
        )
    return ingest  # type: ignore[no-any-return]


def analyze_of(request: Request) -> CreateAnalysis:
    """Analysis-identity use case."""
    analyze = getattr(request.app.state, "analyze", None)
    if analyze is None:
        raise ApiError(
            SafeError(
                code="RESOURCE_STATE",
                message="analysis identity is not configured",
                retryable=True,
                stage="control",
                request_id=request_id_of(request),
            ),
            503,
        )
    return analyze  # type: ignore[no-any-return]
