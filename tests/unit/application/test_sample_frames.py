"""JPEG byte cache: overlapping purposes read a storage key once."""

from pathlib import Path
from uuid import uuid4

from tests.factories import ANALYSIS_ID, SAMPLE_ID, SHOT_ID, VIDEO_ID, make_artifact
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.sample_frames import (
    jpeg_cache_stats,
    jpeg_read_cache,
    last_jpeg_cache_stats,
    load_decoded_jpegs,
)
from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleRequest,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
)
from cine_analyzer.domain.types import SCHEMA_VERSION


class _CountingStore(MemoryStore):
    def __init__(self, tmp_dir: Path) -> None:
        super().__init__(tmp_dir)
        self.local_calls = 0

    def local_path(self, storage_key: str) -> Path:  # type: ignore[override]
        self.local_calls += 1
        return super().local_path(storage_key)


def _manifest(*, extra: SampleResult | None = None) -> SamplingManifest:
    unavailable_id = uuid4()
    results = [
        SampleResult(
            sample_id=SAMPLE_ID,
            shot_id=SHOT_ID,
            requested_ms=0,
            decoded_ms=0,
            purposes=(SamplePurpose.CHROMATIC, SamplePurpose.COMPOSITION, SamplePurpose.MOTION),
            status=SampleStatus.DECODED,
            image=make_artifact(),
        ),
        SampleResult(
            sample_id=unavailable_id,
            shot_id=SHOT_ID,
            requested_ms=10,
            purposes=(SamplePurpose.CHROMATIC,),
            status=SampleStatus.UNAVAILABLE,
            unavailable_reason="decoder returned no frame",
        ),
    ]
    requests = [
        SampleRequest(
            sample_id=SAMPLE_ID,
            shot_id=SHOT_ID,
            requested_ms=0,
            purposes=(SamplePurpose.CHROMATIC, SamplePurpose.COMPOSITION, SamplePurpose.MOTION),
        ),
        SampleRequest(
            sample_id=unavailable_id,
            shot_id=SHOT_ID,
            requested_ms=10,
            purposes=(SamplePurpose.CHROMATIC,),
        ),
    ]
    if extra is not None:
        results.append(extra)
        requests.append(
            SampleRequest(
                sample_id=extra.sample_id,
                shot_id=extra.shot_id,
                requested_ms=extra.requested_ms,
                purposes=extra.purposes,
            )
        )
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        requests=tuple(requests),
    )
    return SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        plan=plan,
        results=tuple(results),
    )


def test_cache_collapses_three_purpose_reads_to_one(tmp_path: Path) -> None:
    store = _CountingStore(tmp_path)
    key = "aa/" + "a" * 64
    store.blobs[key] = b"jpeg"
    keys = {SAMPLE_ID: key}
    manifest = _manifest()
    load_decoded_jpegs(manifest, keys, store, SHOT_ID, SamplePurpose.CHROMATIC)
    load_decoded_jpegs(manifest, keys, store, SHOT_ID, SamplePurpose.COMPOSITION)
    load_decoded_jpegs(manifest, keys, store, SHOT_ID, SamplePurpose.MOTION)
    assert store.local_calls == 3
    with jpeg_read_cache() as stats:
        assert jpeg_cache_stats() is stats
        load_decoded_jpegs(manifest, keys, store, SHOT_ID, SamplePurpose.CHROMATIC)
        load_decoded_jpegs(manifest, keys, store, SHOT_ID, SamplePurpose.COMPOSITION)
        load_decoded_jpegs(manifest, keys, store, SHOT_ID, SamplePurpose.MOTION)
    assert jpeg_cache_stats() is None
    assert store.local_calls == 4
    stats = last_jpeg_cache_stats()
    assert stats is not None
    assert stats.reads == 1
    assert stats.hits == 2


def test_missing_key_wrong_shot_and_purpose_are_skipped(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    manifest = _manifest(
        extra=SampleResult(
            sample_id=uuid4(),
            shot_id=SHOT_ID,
            requested_ms=20,
            decoded_ms=20,
            purposes=(SamplePurpose.CHROMATIC,),
            status=SampleStatus.DECODED,
            image=make_artifact(),
        )
    )
    frames = load_decoded_jpegs(manifest, {}, store, SHOT_ID, SamplePurpose.CHROMATIC)
    assert frames == ()
    other = load_decoded_jpegs(manifest, {}, store, uuid4(), SamplePurpose.CHROMATIC)
    assert other == ()
    evidence = load_decoded_jpegs(manifest, {}, store, SHOT_ID, SamplePurpose.EVIDENCE)
    assert evidence == ()
