"""Client-visible errors. Internal traces never leave this shape."""

from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import Field, model_validator

from cine_analyzer.domain.types import StrictModel

__all__ = [
    "ERROR_PREFIXES",
    "ErrorPrefix",
    "RetryClass",
    "SafeError",
    "retry_class_for",
]


class ErrorPrefix(StrEnum):
    """Stable prefixes for ``SafeError.code``. The rest of the code is specific."""

    MEDIA = "MEDIA_"
    PROBE = "PROBE_"
    SHOT = "SHOT_"
    ARTIFACT = "ARTIFACT_"
    MODEL = "MODEL_"
    RESOURCE = "RESOURCE_"
    SCHEMA = "SCHEMA_"
    CANCELED = "CANCELED_"


class RetryClass(StrEnum):
    """Declared retry behaviour for a prefix. Workers still decide per-code."""

    TERMINAL = "terminal"
    TRANSIENT = "transient"
    BOUNDED = "bounded"
    DEGRADE_OR_RETRY = "degrade_or_retry"
    TERMINAL_CANCELED = "terminal_canceled"


ERROR_PREFIXES: Final[tuple[ErrorPrefix, ...]] = tuple(ErrorPrefix)

_RETRY_BY_PREFIX: Final[dict[ErrorPrefix, RetryClass]] = {
    ErrorPrefix.MEDIA: RetryClass.TERMINAL,
    ErrorPrefix.PROBE: RetryClass.TRANSIENT,
    ErrorPrefix.SHOT: RetryClass.BOUNDED,
    ErrorPrefix.ARTIFACT: RetryClass.TRANSIENT,
    ErrorPrefix.MODEL: RetryClass.TERMINAL,
    ErrorPrefix.RESOURCE: RetryClass.DEGRADE_OR_RETRY,
    ErrorPrefix.SCHEMA: RetryClass.TERMINAL,
    ErrorPrefix.CANCELED: RetryClass.TERMINAL_CANCELED,
}


def retry_class_for(code: str) -> RetryClass:
    """Return the retry class implied by a code's prefix."""
    for prefix in ERROR_PREFIXES:
        if code.startswith(prefix.value):
            return _RETRY_BY_PREFIX[prefix]
    message = f"unrecognised error code prefix in {code!r}"
    raise ValueError(message)


class SafeError(StrictModel):
    """The only error shape exposed to clients. No paths, no stderr, no frames."""

    code: Annotated[str, Field(min_length=1, max_length=64)]
    message: Annotated[str, Field(min_length=1, max_length=512)]
    retryable: bool
    stage: str | None = None
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    details: tuple[dict[str, str], ...] = ()

    @model_validator(mode="after")
    def code_uses_a_known_prefix(self) -> Self:
        retry_class_for(self.code)
        return self
