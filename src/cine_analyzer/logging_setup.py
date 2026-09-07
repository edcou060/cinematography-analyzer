"""Structured logging.

Two properties matter here and both are tested.

*Context is not global.* Correlation identifiers are bound into ``contextvars``,
so a stage running concurrently with another in the same process cannot read or
overwrite its neighbour's ``analysis_id``. There is no module-level dictionary of
"the current job".

*Serialization is total.* A log call is diagnostic code. It renders whatever it
was handed, including objects with no JSON representation, without raising and
without taking the caller down with it. Keys that look like credentials are
replaced before they reach the renderer.

Field vocabulary follows ``docs/operations/quality-and-operations.md`` section 8.
"""

import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final, TextIO, cast

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

if TYPE_CHECKING:
    from structlog.typing import FilteringBoundLogger

    from cine_analyzer.settings import Settings

__all__ = [
    "PATH_KEYS",
    "REDACTED",
    "SENSITIVE_KEY_MARKERS",
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_logger",
]

REDACTED: Final = "[redacted]"

SENSITIVE_KEY_MARKERS: Final = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "passwd",
    "password",
    "private_key",
    "secret",
    "session_key",
    "signature",
    "signed_url",
    "token",
)

PATH_KEYS: Final = frozenset(
    {
        "path",
        "local_path",
        "filename",
        "original_filename",
        "filepath",
        "stderr",
        "argv",
    }
)


_SEPARATORS = re.compile(r"[^a-z0-9]+")


def _normalise(key: str) -> str:
    """Fold case and drop separators, so ``X-Api-Key`` and ``api_key`` compare equal.

    HTTP header names arrive hyphenated and field names arrive with underscores.
    Matching the raw text would redact one spelling and leak the other.
    """
    return _SEPARATORS.sub("", key.lower())


_NORMALISED_MARKERS: Final = tuple(_normalise(marker) for marker in SENSITIVE_KEY_MARKERS)


def _is_sensitive(key: str) -> bool:
    normalised = _normalise(key)
    return any(marker in normalised for marker in _NORMALISED_MARKERS)


def _looks_like_host_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    if lowered.startswith(("/users/", "/home/", "/private/", "/var/folders/")):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}


def _redact_sensitive(
    _logger: WrappedLogger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Replace credential keys, path-like keys, and host-path values."""
    for key in list(event_dict):
        name = str(key)
        if _is_sensitive(name) or name.lower() in PATH_KEYS:
            event_dict[key] = REDACTED
            continue
        if _looks_like_host_path(event_dict[key]):
            event_dict[key] = REDACTED
    return event_dict


def _service_stamper(service: str) -> Processor:
    def add_service(
        _logger: WrappedLogger,
        _method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        event_dict.setdefault("service", service)
        return event_dict

    return add_service


def _renderer(log_format: str) -> Processor:
    if log_format == "console":
        return structlog.dev.ConsoleRenderer(colors=False)
    # default=str is what makes serialization total: an object json cannot encode
    # is stringified rather than raising inside a log call.
    return structlog.processors.JSONRenderer(default=str, sort_keys=True)


def configure_logging(settings: "Settings", *, stream: TextIO | None = None) -> None:
    """Install the process-wide logging configuration.

    Call once, explicitly, from an entry point. Importing any module of this
    package must never call it.

    Args:
        settings: validated settings supplying level, format, and service name.
        stream: destination for rendered events. Defaults to ``sys.stderr`` so
            log output never contaminates a command's stdout.
    """
    destination = sys.stderr if stream is None else stream
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _service_stamper(settings.service_name),
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive,
        _renderer(settings.log_format),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level],
        ),
        logger_factory=structlog.WriteLoggerFactory(file=destination),
        # False so a reconfiguration is honoured immediately. Caching is a
        # throughput optimisation to revisit with a measurement, not a guess.
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> "FilteringBoundLogger":
    """Return a logger tagged with the emitting module's name."""
    return cast("FilteringBoundLogger", structlog.get_logger().bind(logger=name))


@contextmanager
def bind_context(  # noqa: PLR0913 - one keyword per documented log field, by design
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    analysis_id: str | None = None,
    video_id: str | None = None,
    stage: str | None = None,
    attempt: int | None = None,
    worker_id: str | None = None,
) -> Iterator[None]:
    """Bind correlation fields for the duration of the block.

    Only the documented field vocabulary is accepted, so the log schema stays
    greppable instead of accumulating one-off key names. ``None`` arguments are
    dropped rather than logged as nulls. Previous values are restored on exit,
    including when the block raises.
    """
    candidates: dict[str, str | int | None] = {
        "request_id": request_id,
        "trace_id": trace_id,
        "analysis_id": analysis_id,
        "video_id": video_id,
        "stage": stage,
        "attempt": attempt,
        "worker_id": worker_id,
    }
    bound = {key: value for key, value in candidates.items() if value is not None}
    with structlog.contextvars.bound_contextvars(**bound):
        yield


def clear_context() -> None:
    """Drop every bound correlation field in the current context."""
    structlog.contextvars.clear_contextvars()
