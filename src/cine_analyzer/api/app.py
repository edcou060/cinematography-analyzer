"""Thin FastAPI control plane. Must not import OpenCV, PyAV, or PySceneDetect."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from cine_analyzer import __version__
from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.adapters.persistence.postgres import PostgresJobRepository
from cine_analyzer.api.errors import (
    ApiError,
    safe_response,
    starlette_error_envelope,
)
from cine_analyzer.api.errors import (
    _rid as request_id_from,
)
from cine_analyzer.api.routes import (
    analyses_router,
    artifacts_router,
    health_router,
    videos_router,
)
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.errors import AdapterError, IngestError
from cine_analyzer.application.ingest import IngestVideo
from cine_analyzer.domain.errors import SafeError
from cine_analyzer.logging_setup import bind_context
from cine_analyzer.ports.control import JobRepository
from cine_analyzer.ports.ingestion import ArtifactStore
from cine_analyzer.settings import Settings, load_settings

__all__ = ["OPENAPI_SNAPSHOT", "create_app"]

OPENAPI_SNAPSHOT = (
    Path(__file__).resolve().parents[3] / "tests" / "contract" / "api" / "openapi.json"
)


def create_app(
    *,
    settings: Settings | None = None,
    jobs: JobRepository | None = None,
    store: ArtifactStore | None = None,
    ingest: IngestVideo | None = None,
    analyze: CreateAnalysis | None = None,
) -> FastAPI:
    """Build the API. Injected ports are for tests; production uses PostgreSQL."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns = False
        bound = settings if settings is not None else load_settings()
        app.state.settings = bound
        if getattr(app.state, "jobs", None) is None:
            if bound.database_url is None:
                app.state.jobs = None
                app.state.store = None
                app.state.ingest = None
                app.state.analyze = None
            else:
                repository = PostgresJobRepository(bound.database_url)
                artifact_store = FilesystemArtifactStore(bound.artifact_root)
                probe = FfprobeMediaProbe(
                    bound.ffprobe_binary,
                    timeout_ms=bound.ffprobe_timeout_ms,
                )
                app.state.jobs = repository
                app.state.store = artifact_store
                app.state.ingest = IngestVideo(
                    artifact_store,
                    probe,
                    repository,
                    chunk_bytes=bound.ingest_chunk_bytes,
                    min_free_bytes=bound.min_free_bytes,
                )
                app.state.analyze = CreateAnalysis(repository)
                owns = True
        try:
            yield
        finally:
            if owns:
                closer = getattr(app.state.jobs, "close", None)
                if callable(closer):
                    closer()

    app = FastAPI(
        title="cine-analyzer",
        version=__version__,
        summary="Reproducible cinematography measurement control plane.",
        lifespan=lifespan,
    )
    if jobs is not None:
        app.state.jobs = jobs
        app.state.store = store
        app.state.ingest = ingest
        app.state.analyze = analyze
        app.state.settings = settings if settings is not None else load_settings()

    app.include_router(health_router)
    app.include_router(videos_router)
    app.include_router(analyses_router)
    app.include_router(artifacts_router)

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("x-request-id", "").strip()
        request.state.request_id = incoming or uuid4().hex
        with bind_context(request_id=request.state.request_id, trace_id=request.state.request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, error: ApiError) -> JSONResponse:
        return safe_response(error.safe, status_code=error.status_code)

    @app.exception_handler(IngestError)
    async def ingest_error_handler(_request: Request, error: IngestError) -> JSONResponse:
        return safe_response(error.safe)

    @app.exception_handler(AdapterError)
    async def adapter_error_handler(request: Request, error: AdapterError) -> JSONResponse:
        return safe_response(
            SafeError(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                stage=error.stage or "control",
                request_id=request_id_from(request),
            )
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        details = tuple(
            {
                "field": ".".join(str(part) for part in item.get("loc", ())),
                "message": str(item.get("msg", "invalid")),
            }
            for item in error.errors()
        )
        return safe_response(
            SafeError(
                code="SCHEMA_INVALID",
                message="the request does not match the public schema",
                retryable=False,
                stage="control",
                request_id=request_id_from(request),
                details=details,
            ),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        code, status_code, message = starlette_error_envelope(error.status_code)
        return safe_response(
            SafeError(
                code=code,
                message=message,
                retryable=False,
                stage="control",
                request_id=request_id_from(request),
            ),
            status_code=status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, _error: Exception) -> JSONResponse:
        return safe_response(
            SafeError(
                code="RESOURCE_STATE",
                message="the request could not be completed",
                retryable=True,
                stage="control",
                request_id=request_id_from(request),
            ),
            status_code=500,
        )

    return app
