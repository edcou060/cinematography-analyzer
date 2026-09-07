"""Load decoded sample JPEGs for one shot and purpose."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from cine_analyzer.domain.media import SamplePurpose, SampleResult, SampleStatus, SamplingManifest
from cine_analyzer.observability.metrics import incr
from cine_analyzer.ports.ingestion import ArtifactStore

__all__ = [
    "JpegCacheStats",
    "jpeg_cache_stats",
    "jpeg_read_cache",
    "last_jpeg_cache_stats",
    "load_decoded_jpegs",
    "reset_jpeg_cache_stats",
]


@dataclass
class JpegCacheStats:
    """Per-context read and hit counts. Not a metric formula."""

    reads: int = 0
    hits: int = 0


_jpeg_ctx: ContextVar[tuple[dict[str, bytes], JpegCacheStats] | None] = ContextVar(
    "jpeg_ctx", default=None
)
_last_completed: list[JpegCacheStats | None] = [None]


@contextmanager
def jpeg_read_cache() -> Iterator[JpegCacheStats]:
    """Memoize sample JPEG bytes for the duration of one report assemble."""
    stats = JpegCacheStats()
    token = _jpeg_ctx.set(({}, stats))
    try:
        yield stats
    finally:
        _last_completed[0] = JpegCacheStats(reads=stats.reads, hits=stats.hits)
        _jpeg_ctx.reset(token)


def jpeg_cache_stats() -> JpegCacheStats | None:
    """Return the active cache stats, or None outside ``jpeg_read_cache``."""
    ctx = _jpeg_ctx.get()
    if ctx is None:
        return None
    return ctx[1]


def last_jpeg_cache_stats() -> JpegCacheStats | None:
    """Stats from the most recently closed ``jpeg_read_cache`` block."""
    return _last_completed[0]


def reset_jpeg_cache_stats() -> None:
    """Drop completed stats. Tests only."""
    _last_completed[0] = None


def load_decoded_jpegs(
    manifest: SamplingManifest,
    sample_keys: dict[UUID, str],
    store: ArtifactStore,
    shot_id: UUID,
    purpose: SamplePurpose,
) -> tuple[tuple[UUID, bytes], ...]:
    """Return ``(sample_id, jpeg)`` pairs in manifest order."""
    frames: list[tuple[UUID, bytes]] = []
    for result in manifest.results:
        if result.shot_id != shot_id:
            continue
        if purpose not in result.purposes:
            continue
        jpeg = _jpeg_bytes_for(result, sample_keys, store)
        if jpeg is None:
            continue
        frames.append((result.sample_id, jpeg))
    return tuple(frames)


def _jpeg_bytes_for(
    result: SampleResult,
    sample_keys: dict[UUID, str],
    store: ArtifactStore,
) -> bytes | None:
    if result.status is not SampleStatus.DECODED:
        return None
    key = sample_keys.get(result.sample_id)
    if key is None:
        return None
    ctx = _jpeg_ctx.get()
    if ctx is not None and key in ctx[0]:
        ctx[1].hits += 1
        incr("cache_hits_total", stage="report")
        return ctx[0][key]
    data = store.local_path(key).read_bytes()
    if ctx is not None:
        ctx[1].reads += 1
        ctx[0][key] = data
    return data
