"""Cooperative cancel between shots and samples."""

from pathlib import Path

import pytest
from tests.unit.application.fakes import (
    REQUEST_ID,
    FakeRepository,
    MemoryStore,
    tiny_config,
    video_record_from_bytes,
)
from tests.unit.sampling.test_pipeline import _Detector, _Extractor

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.errors import IngestError, ingest_error
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.application.stage_execute import tick_cancel
from cine_analyzer.domain.shots import TransitionKind
from cine_analyzer.ports.shots import DetectedBoundary, DetectionResult


def test_tick_cancel_invokes_the_hook() -> None:
    seen = {"n": 0}

    def hook() -> None:
        seen["n"] += 1

    tick_cancel(hook)
    assert seen["n"] == 1
    tick_cancel(None)


def test_sampling_honors_cancel_after_detection(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.blobs[video.original_storage_key] = b"clip-bytes"
    repo.insert_video(video)
    created = CreateAnalysis(repo).execute(video=video, config=tiny_config(), request_id=REQUEST_ID)
    detector = _Detector(
        DetectionResult(
            boundaries=(
                DetectedBoundary(
                    position_ms=2000, transition=TransitionKind.CUT, detector_score=0.9
                ),
            ),
            debug_stats=None,
        )
    )
    pipeline = RunSamplingStages(store, detector, _Extractor({}), repo)

    def cancel() -> None:
        raise ingest_error(
            "CANCELED_BY_CLIENT",
            "canceled",
            request_id=REQUEST_ID,
            retryable=False,
            stage="sampling",
        )

    with pytest.raises(IngestError, match="canceled"):
        pipeline.execute(
            video=video,
            analysis=created.analysis,
            config=tiny_config(),
            request_id=REQUEST_ID,
            cancel_check=cancel,
        )
