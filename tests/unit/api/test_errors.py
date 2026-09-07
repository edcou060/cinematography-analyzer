"""SafeError HTTP mapping does not leak internals."""

from unittest.mock import Mock

from cine_analyzer.api.errors import (
    http_status_for,
    ingest_to_api,
    not_found_video,
    schema_invalid,
    starlette_error_envelope,
)
from cine_analyzer.application.errors import ingest_error
from cine_analyzer.domain.errors import SafeError


def _safe(*, code: str, retryable: bool) -> SafeError:
    return SafeError(
        code=code,
        message="safe",
        retryable=retryable,
        stage="control",
        request_id="req",
    )


def test_http_status_for_maps_stable_codes() -> None:
    assert http_status_for(_safe(code="MEDIA_TOO_LARGE", retryable=False)) == 413
    assert http_status_for(_safe(code="MEDIA_NOT_FOUND", retryable=False)) == 404
    assert http_status_for(_safe(code="ARTIFACT_MISSING", retryable=False)) == 404
    assert http_status_for(_safe(code="SCHEMA_INVALID", retryable=False)) == 422
    assert http_status_for(_safe(code="RESOURCE_NOT_READY", retryable=True)) == 409
    assert http_status_for(_safe(code="RESOURCE_LIMIT", retryable=True)) == 429
    assert http_status_for(_safe(code="RESOURCE_STATE", retryable=True)) == 503
    assert http_status_for(_safe(code="MEDIA_EMPTY", retryable=False)) == 400


def test_starlette_error_envelope_covers_fallback() -> None:
    assert starlette_error_envelope(404)[1] == 404
    assert starlette_error_envelope(405)[1] == 405
    assert starlette_error_envelope(401) == (
        "SCHEMA_INVALID",
        400,
        "the request could not be processed",
    )


def test_ingest_to_api_and_missing_request_id() -> None:
    wrapped = ingest_to_api(ingest_error("MEDIA_EMPTY", "empty", request_id="req", retryable=False))
    assert wrapped.status_code == 400
    request = Mock()
    request.state.request_id = None
    assert schema_invalid(request, "bad").safe.request_id == "missing-request-id"
    request.state.request_id = 12
    assert not_found_video(request).safe.code == "MEDIA_NOT_FOUND"
    request.state.request_id = "keep-me"
    assert schema_invalid(request, "bad").safe.request_id == "keep-me"
