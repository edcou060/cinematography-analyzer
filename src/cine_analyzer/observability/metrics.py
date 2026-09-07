"""Process-local counters and millisecond histograms with closed label sets."""

from threading import Lock
from typing import Final

from cine_analyzer.domain.errors import ErrorPrefix
from cine_analyzer.domain.jobs import AnalysisState, StageState
from cine_analyzer.domain.types import StrictModel

__all__ = [
    "CounterEntry",
    "GaugeEntry",
    "HistogramEntry",
    "MetricsSnapshot",
    "error_class_for",
    "incr",
    "observe",
    "reset_metrics",
    "snapshot",
]

_LOCK = Lock()
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
_histograms: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[int, int, int]] = {}

_STAGE_VALUES: Final = frozenset(
    {
        "ingest",
        "analyze",
        "sampling",
        "report",
        "aggregate",
        "probe",
        "control",
        "spatial",
        "worker",
        "cleanup",
        "benchmark",
        "chromatic",
        "motion",
        "audio",
        "shots",
        "other",
    }
)
_STATE_VALUES: Final = frozenset(
    {item.value for item in AnalysisState}
    | {item.value for item in StageState}
    | {
        "succeeded",
        "skipped",
        "canceled",
        "failed",
        "lease_lost",
        "ok",
        "unavailable",
        "none",
        "other",
    }
)
_QUEUE_VALUES: Final = frozenset(
    {
        "ingest",
        "cpu_decode",
        "cpu_analysis",
        "gpu_spatial",
        "critic",
        "local",
        "other",
    }
)
_ERROR_CLASS_VALUES: Final = frozenset(
    {prefix.value.rstrip("_") for prefix in ErrorPrefix} | {"none", "other"}
)
_KIND_VALUES: Final = frozenset(
    {"original", "probe", "sample", "report", "timeline", "canonical", "other"}
)
_OPERATION_VALUES: Final = frozenset({"write", "read", "promote", "delete", "other"})
_REASON_VALUES: Final = frozenset(
    {
        "MEDIA_TOO_LARGE",
        "MEDIA_EMPTY",
        "MEDIA_UNREADABLE",
        "MEDIA_CORRUPT",
        "MEDIA_UNSUPPORTED_CODEC",
        "MEDIA_UNSUPPORTED_TRANSFER",
        "MEDIA_VIDEO_STREAM_COUNT",
        "MEDIA_AUDIO_STREAM_COUNT",
        "MEDIA_DIMENSIONS_INVALID",
        "MEDIA_DIMENSIONS_EXCEEDED",
        "MEDIA_DURATION_INVALID",
        "MEDIA_DURATION_EXCEEDED",
        "MEDIA_UNSUPPORTED_ROTATION",
        "MEDIA_FRAME_RATE_UNKNOWN",
        "MEDIA_UNEXPECTED_STREAM",
        "MEDIA_AUDIO_INCONSISTENT",
        "RESOURCE_DISK",
        "RESOURCE_LIMIT",
        "other",
    }
)
_SPAN_VALUES: Final = frozenset({"queue_wait", "compute", "artifact_io", "model_batch", "other"})
_PROFILE_VALUES: Final = frozenset({"cpu_core", "local", "celery", "other"})
_MODEL_VALUES: Final = frozenset({"fake", "none", "ultralytics", "other"})

_LABEL_VALUES: Final[dict[str, frozenset[str]]] = {
    "stage": _STAGE_VALUES,
    "state": _STATE_VALUES,
    "queue": _QUEUE_VALUES,
    "error_class": _ERROR_CLASS_VALUES,
    "kind": _KIND_VALUES,
    "operation": _OPERATION_VALUES,
    "reason": _REASON_VALUES,
    "span": _SPAN_VALUES,
    "profile": _PROFILE_VALUES,
    "model": _MODEL_VALUES,
}

_METRIC_LABELS: Final[dict[str, frozenset[str]]] = {
    "analysis_jobs_total": frozenset({"state"}),
    "stage_runs_total": frozenset({"stage", "state", "error_class"}),
    "stage_duration_ms": frozenset({"stage"}),
    "queue_wait_ms": frozenset({"queue"}),
    "span_duration_ms": frozenset({"span"}),
    "artifact_write_bytes_total": frozenset({"kind"}),
    "artifact_failures_total": frozenset({"operation"}),
    "cache_hits_total": frozenset({"stage"}),
    "upload_rejections_total": frozenset({"reason"}),
    "analysis_realtime_factor_milli": frozenset({"profile"}),
    "model_oom_total": frozenset({"model"}),
    "model_inference_batch_ms": frozenset({"model"}),
}


class CounterEntry(StrictModel):
    """One labeled counter."""

    name: str
    labels: tuple[tuple[str, str], ...]
    value: int


class HistogramEntry(StrictModel):
    """One labeled millisecond histogram summary."""

    name: str
    labels: tuple[tuple[str, str], ...]
    count: int
    sum_ms: int
    max_ms: int


class GaugeEntry(StrictModel):
    """A point-in-time gauge. Not stored in the counter map."""

    name: str
    value: int


class MetricsSnapshot(StrictModel):
    """JSON scrape payload for ``GET /metrics``."""

    counters: tuple[CounterEntry, ...]
    histograms: tuple[HistogramEntry, ...]
    gauges: tuple[GaugeEntry, ...]


def error_class_for(code: str | None) -> str:
    """Map a SafeError code to a bounded error-class label."""
    if code is None:
        return "none"
    for prefix in ErrorPrefix:
        if code.startswith(prefix.value):
            return prefix.value.rstrip("_")
    return "other"


def reset_metrics() -> None:
    """Drop every series. Tests and process start only."""
    with _LOCK:
        _counters.clear()
        _histograms.clear()


def incr(name: str, amount: int = 1, **labels: str) -> None:
    """Add to a counter. Unknown names raise; unknown label values become ``other``."""
    key = _series_key(name, labels)
    with _LOCK:
        _counters[key] = _counters.get(key, 0) + amount


def observe(name: str, value_ms: int, **labels: str) -> None:
    """Record a non-negative millisecond sample."""
    sample = 0 if value_ms < 0 else value_ms
    key = _series_key(name, labels)
    with _LOCK:
        count, total, peak = _histograms.get(key, (0, 0, 0))
        _histograms[key] = (count + 1, total + sample, max(peak, sample))


def snapshot(*, active_jobs: int = 0) -> MetricsSnapshot:
    """Copy the registry. ``active_jobs`` is supplied by the scrape, not stored."""
    with _LOCK:
        counters = tuple(
            CounterEntry(name=name, labels=labels, value=value)
            for (name, labels), value in sorted(_counters.items(), key=lambda item: item[0])
        )
        histograms = tuple(
            HistogramEntry(
                name=name,
                labels=labels,
                count=count,
                sum_ms=total,
                max_ms=peak,
            )
            for (name, labels), (count, total, peak) in sorted(
                _histograms.items(), key=lambda item: item[0]
            )
        )
    return MetricsSnapshot(
        counters=counters,
        histograms=histograms,
        gauges=(GaugeEntry(name="analysis_active_jobs", value=active_jobs),),
    )


def _series_key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    allowed = _METRIC_LABELS.get(name)
    if allowed is None:
        message = f"unknown metric {name!r}"
        raise ValueError(message)
    extra = set(labels) - allowed
    if extra:
        message = f"unexpected labels {sorted(extra)} for metric {name!r}"
        raise ValueError(message)
    missing = allowed - set(labels)
    if missing:
        message = f"missing labels {sorted(missing)} for metric {name!r}"
        raise ValueError(message)
    cleaned: list[tuple[str, str]] = []
    for key, value in sorted(labels.items()):
        permitted = _LABEL_VALUES[key]
        cleaned.append((key, value if value in permitted else "other"))
    return name, tuple(cleaned)
