"""Stage/batch spans as structured log events. No per-frame spans."""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from cine_analyzer.logging_setup import get_logger
from cine_analyzer.observability.metrics import observe

__all__ = ["record_queue_wait", "span"]


@contextmanager
def span(name: str, **fields: object) -> Iterator[None]:
    """Log ``span.closed`` with duration_ms and observe ``span_duration_ms``."""
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        get_logger(__name__).info("span.closed", span=name, duration_ms=duration_ms, **fields)
        observe("span_duration_ms", duration_ms, span=str(name))


def record_queue_wait(*, queue: str, wait_ms: int) -> None:
    """Separate queue wait from compute. ``wait_ms`` is clamped at zero."""
    wait = max(0, wait_ms)
    get_logger(__name__).info("span.closed", span="queue_wait", duration_ms=wait, queue=queue)
    observe("queue_wait_ms", wait, queue=queue)
    observe("span_duration_ms", wait, span="queue_wait")
