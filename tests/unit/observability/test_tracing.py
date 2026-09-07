"""Queue-wait vs compute spans."""

import io
import json

from cine_analyzer.logging_setup import configure_logging
from cine_analyzer.observability.metrics import snapshot
from cine_analyzer.observability.tracing import record_queue_wait, span
from cine_analyzer.settings import Settings


def test_span_and_queue_wait_are_logged_and_observed() -> None:
    stream = io.StringIO()
    configure_logging(Settings(), stream=stream)
    with span("compute", stage="sampling"):
        pass
    record_queue_wait(queue="cpu_decode", wait_ms=-3)
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    names = [event["span"] for event in events if event["event"] == "span.closed"]
    assert "compute" in names
    assert "queue_wait" in names
    hist = snapshot().histograms
    assert any(item.name == "queue_wait_ms" and item.sum_ms == 0 for item in hist)
