"""Safe, client-visible ingest failures. Paths never appear in the message."""

from cine_analyzer.domain.errors import SafeError

__all__ = ["AdapterError", "IngestError", "ingest_error", "wrap_adapter"]


class IngestError(Exception):
    """Raised when ingest or analysis-identity creation cannot proceed."""

    def __init__(self, safe: SafeError) -> None:
        self.safe = safe
        super().__init__(safe.message)


class AdapterError(Exception):
    """Adapter failure before a request id exists. The use case wraps it."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        stage: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.stage = stage
        super().__init__(message)


def ingest_error(
    code: str,
    message: str,
    *,
    request_id: str,
    retryable: bool,
    stage: str | None = "ingest",
) -> IngestError:
    """Build an ingest error with a SafeError payload."""
    return IngestError(
        SafeError(
            code=code,
            message=message,
            retryable=retryable,
            stage=stage,
            request_id=request_id,
        )
    )


def wrap_adapter(
    error: AdapterError,
    *,
    request_id: str,
    stage: str | None = None,
) -> IngestError:
    """Attach a request id to an adapter failure without copying paths or stderr."""
    resolved = error.stage if stage is None else stage
    if resolved is None:
        resolved = "probe" if error.code.startswith("PROBE_") else "ingest"
    return ingest_error(
        error.code,
        error.message,
        request_id=request_id,
        retryable=error.retryable,
        stage=resolved,
    )
