"""HTTP problem details. Paths and stderr never appear in the payload."""

from fastapi import Request
from fastapi.responses import JSONResponse

from cine_analyzer.application.errors import IngestError
from cine_analyzer.domain.errors import SafeError

__all__ = [
    "ApiError",
    "http_status_for",
    "safe_response",
    "starlette_error_envelope",
]


class ApiError(Exception):
    """Control-plane failure with a SafeError body and HTTP status."""

    def __init__(self, safe: SafeError, status_code: int) -> None:
        self.safe = safe
        self.status_code = status_code
        super().__init__(safe.message)


def http_status_for(safe: SafeError) -> int:
    """Map a SafeError to a coarse HTTP status without leaking internals."""
    if safe.code == "MEDIA_TOO_LARGE":
        return 413
    if safe.code in {"MEDIA_NOT_FOUND", "ARTIFACT_MISSING"}:
        return 404
    if safe.code.startswith("SCHEMA_"):
        return 422
    if safe.code == "RESOURCE_NOT_READY":
        return 409
    if safe.code == "RESOURCE_LIMIT":
        return 429
    if safe.retryable:
        return 503
    return 400


def starlette_error_envelope(status_code: int) -> tuple[str, int, str]:
    """SafeError fields for a Starlette HTTPException."""
    if status_code == 404:
        return ("ARTIFACT_MISSING", 404, "the requested resource was not found")
    if status_code == 405:
        return ("SCHEMA_INVALID", 405, "the request could not be processed")
    return ("SCHEMA_INVALID", 400, "the request could not be processed")


def safe_response(safe: SafeError, *, status_code: int | None = None) -> JSONResponse:
    """JSON SafeError with the correlation id echoed on the response."""
    code = http_status_for(safe) if status_code is None else status_code
    response = JSONResponse(content=safe.model_dump(mode="json"), status_code=code)
    response.headers["X-Request-ID"] = safe.request_id
    return response


def ingest_to_api(error: IngestError) -> ApiError:
    """Wrap an ingest failure for the HTTP handler."""
    return ApiError(error.safe, http_status_for(error.safe))


def not_found_video(request: Request) -> ApiError:
    return ApiError(
        SafeError(
            code="MEDIA_NOT_FOUND",
            message="the video was not found",
            retryable=False,
            stage="control",
            request_id=_rid(request),
        ),
        404,
    )


def not_found_artifact(request: Request) -> ApiError:
    return ApiError(
        SafeError(
            code="ARTIFACT_MISSING",
            message="the requested resource was not found",
            retryable=False,
            stage="control",
            request_id=_rid(request),
        ),
        404,
    )


def not_ready(request: Request) -> ApiError:
    return ApiError(
        SafeError(
            code="RESOURCE_NOT_READY",
            message="the analysis report is not ready",
            retryable=True,
            stage="control",
            request_id=_rid(request),
        ),
        409,
    )


def schema_invalid(request: Request, message: str) -> ApiError:
    return ApiError(
        SafeError(
            code="SCHEMA_INVALID",
            message=message,
            retryable=False,
            stage="control",
            request_id=_rid(request),
        ),
        422,
    )


def _rid(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    return "missing-request-id"
