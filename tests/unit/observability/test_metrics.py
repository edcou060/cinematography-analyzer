"""In-process metrics: closed names and coerced labels."""

import pytest

from cine_analyzer.observability import incr as package_incr
from cine_analyzer.observability.metrics import (
    error_class_for,
    incr,
    observe,
    reset_metrics,
    snapshot,
)


def test_counters_histograms_and_active_gauge() -> None:
    package_incr("analysis_jobs_total", state="QUEUED")
    observe("stage_duration_ms", 12, stage="sampling")
    observe("stage_duration_ms", -5, stage="sampling")
    payload = snapshot(active_jobs=4)
    assert payload.gauges[0].value == 4
    assert payload.counters[0].value == 1
    assert payload.histograms[0].count == 2
    assert payload.histograms[0].sum_ms == 12
    reset_metrics()
    assert snapshot().counters == ()


def test_unknown_metric_and_label_shape_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown metric"):
        incr("not_a_metric", state="QUEUED")
    with pytest.raises(ValueError, match="unexpected labels"):
        incr("analysis_jobs_total", state="QUEUED", extra="x")
    with pytest.raises(ValueError, match="missing labels"):
        incr("analysis_jobs_total")


def test_unknown_label_values_become_other_and_error_class_maps() -> None:
    incr("upload_rejections_total", reason="not-a-reason")
    observe("span_duration_ms", 1, span="mystery")
    payload = snapshot()
    assert payload.counters[0].labels == (("reason", "other"),)
    assert payload.histograms[0].labels == (("span", "other"),)
    assert error_class_for(None) == "none"
    assert error_class_for("MEDIA_TOO_LARGE") == "MEDIA"
    assert error_class_for("NOTAPREFIX") == "other"
