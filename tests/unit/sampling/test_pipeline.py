"""Shot and sampling pipeline: coverage, artifacts, unavailable samples."""

from pathlib import Path
from uuid import UUID

import pytest
from tests.unit.application.fakes import (
    REQUEST_ID,
    FakeRepository,
    MemoryStore,
    tiny_config,
    video_record_from_bytes,
)

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.errors import AdapterError, IngestError
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.media import SamplePurpose, SampleStatus
from cine_analyzer.domain.shots import TransitionKind
from cine_analyzer.domain.time import TimeRangeMs
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.ports.shots import DecodedSample, DetectedBoundary, DetectionResult


class _Detector:
    def __init__(self, result: DetectionResult | AdapterError) -> None:
        self.result = result
        self.seen: list[Path] = []

    def detect(self, path: Path, config: object, *, duration_ms: int) -> DetectionResult:
        self.seen.append(path)
        assert duration_ms > 0
        assert config is not None
        if isinstance(self.result, AdapterError):
            raise self.result
        return self.result


class _Extractor:
    def __init__(self, outcomes: dict[UUID, DecodedSample] | AdapterError) -> None:
        self.outcomes = outcomes
        self.rotation: int | None = None

    def extract(
        self,
        path: Path,
        requests: tuple[object, ...],
        ranges: dict[UUID, TimeRangeMs],
        *,
        rotation_degrees: int,
    ) -> tuple[DecodedSample, ...]:
        self.rotation = rotation_degrees
        assert path.exists()
        assert ranges
        if isinstance(self.outcomes, AdapterError):
            raise self.outcomes
        results: list[DecodedSample] = []
        for request in requests:
            sample_id = request.sample_id  # type: ignore[attr-defined]
            if sample_id in self.outcomes:
                results.append(self.outcomes[sample_id])
                continue
            results.append(
                DecodedSample(
                    sample_id=sample_id,
                    requested_ms=request.requested_ms,  # type: ignore[attr-defined]
                    decoded_ms=request.requested_ms,  # type: ignore[attr-defined]
                    frame_index=0,
                    jpeg=b"\xff\xd8fake",
                    unavailable_reason=None,
                )
            )
        return tuple(results)


def _analysis(video: VideoRecord, repo: FakeRepository) -> AnalysisRecord:
    return (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id=REQUEST_ID)
        .analysis
    )


def test_pipeline_persists_contiguous_shots_and_checksummed_frames(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.blobs[video.original_storage_key] = b"clip-bytes"
    analysis = _analysis(video, repo)
    detector = _Detector(
        DetectionResult(
            boundaries=(
                DetectedBoundary(
                    position_ms=2000, transition=TransitionKind.CUT, detector_score=0.9
                ),
            ),
            debug_stats=b"frame,score\n",
        )
    )
    result = RunSamplingStages(store, detector, _Extractor({}), repo).execute(
        video=video,
        analysis=analysis,
        config=tiny_config(),
        request_id=REQUEST_ID,
    )

    assert detector.seen[0].name == video.original_storage_key.replace("/", "_")
    assert len(result.shot_set.shots) == 2
    assert result.shot_set.shots[0].time_range.start_ms == 0
    assert result.shot_set.shots[0].time_range.end_ms == 2000
    assert result.shot_set.shots[1].time_range.end_ms == 4000
    assert result.shot_set.duration_ms() == 4000
    assert all(shot.representative_sample_id is not None for shot in result.shot_set.shots)
    assert store.contains(result.shot_set_key)
    assert store.contains(result.manifest_key)
    assert result.debug_stats_key is not None
    assert store.blobs[result.debug_stats_key] == b"frame,score\n"
    assert result.manifest.results
    decoded = [item for item in result.manifest.results if item.status is SampleStatus.DECODED]
    assert decoded
    assert decoded[0].decoded_ms == decoded[0].requested_ms
    assert decoded[0].image is not None
    assert decoded[0].image.sha256
    kinds = {ref.kind for ref, _key in repo.artifacts}
    assert "shot_set" in kinds
    assert "sampling_manifest" in kinds
    assert "evidence_frame" in kinds
    assert "detector_stats" in kinds
    assert "scene" not in result.shot_set_key
    config = AnalysisConfig()
    assert tiny_config().shots.backend == config.shots.backend


def test_unavailable_and_missing_extracts_are_explicit(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.blobs[video.original_storage_key] = b"clip-bytes"
    analysis = _analysis(video, repo)

    class _PartialExtractor:
        def extract(
            self,
            path: Path,
            requests: tuple[object, ...],
            ranges: dict[UUID, TimeRangeMs],
            *,
            rotation_degrees: int,
        ) -> tuple[DecodedSample, ...]:
            assert path.exists()
            assert ranges
            assert rotation_degrees == 0
            first = requests[0]
            return (
                DecodedSample(
                    sample_id=first.sample_id,  # type: ignore[attr-defined]
                    requested_ms=first.requested_ms,  # type: ignore[attr-defined]
                    decoded_ms=None,
                    frame_index=None,
                    jpeg=None,
                    unavailable_reason="decoded timestamp is outside the requested shot",
                ),
            )

    result = RunSamplingStages(
        store,
        _Detector(DetectionResult(boundaries=(), debug_stats=None)),
        _PartialExtractor(),
        repo,
    ).execute(video=video, analysis=analysis, config=tiny_config(), request_id=REQUEST_ID)

    assert result.debug_stats_key is None
    assert len(result.shot_set.shots) == 1
    assert all(item.status is SampleStatus.UNAVAILABLE for item in result.manifest.results)
    assert result.manifest.results[0].unavailable_reason == (
        "decoded timestamp is outside the requested shot"
    )
    assert any(
        item.unavailable_reason == "sample could not be decoded"
        for item in result.manifest.results[1:]
    )
    assert result.sample_keys == {}
    assert any(SamplePurpose.EVIDENCE in request.purposes for request in result.plan.requests)


def test_adapter_errors_keep_the_stage_and_request_id(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.blobs[video.original_storage_key] = b"clip-bytes"
    analysis = _analysis(video, repo)
    with pytest.raises(IngestError) as caught:
        RunSamplingStages(
            store,
            _Detector(
                AdapterError(
                    "SHOT_FAILED",
                    "shot detection failed",
                    retryable=True,
                    stage="shots",
                )
            ),
            _Extractor({}),
            repo,
        ).execute(video=video, analysis=analysis, config=tiny_config(), request_id=REQUEST_ID)
    assert caught.value.safe.code == "SHOT_FAILED"
    assert caught.value.safe.stage == "shots"
    assert caught.value.safe.request_id == REQUEST_ID
    assert "/tmp" not in caught.value.safe.message


def test_replaceable_stage_json_can_be_rewritten(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.blobs[video.original_storage_key] = b"clip-bytes"
    analysis = _analysis(video, repo)
    pipeline = RunSamplingStages(
        store,
        _Detector(DetectionResult(boundaries=(), debug_stats=None)),
        _Extractor({}),
        repo,
    )
    first = pipeline.execute(
        video=video, analysis=analysis, config=tiny_config(), request_id=REQUEST_ID
    )
    store.blobs[first.shot_set_key] = b'{"stale":true}'
    second = pipeline.execute(
        video=video, analysis=analysis, config=tiny_config(), request_id=REQUEST_ID
    )
    assert second.shot_set_key == first.shot_set_key
    assert store.blobs[second.shot_set_key] != b'{"stale":true}'
    assert b"stale" not in store.blobs[second.shot_set_key]
