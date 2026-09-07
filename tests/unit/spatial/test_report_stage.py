"""Report stage persists spatial.json and overlay JPEGs."""

from pathlib import Path

from tests.factories import SAMPLE_ID, make_ok_chromatic
from tests.unit.application.fakes import (
    FakeRepository,
    MemoryStore,
    make_run_report_stages,
    tiny_config,
    video_record_from_bytes,
)
from tests.unit.chromatic.jpeg_util import encode_jpeg
from tests.unit.spatial.helpers import fake_analyzer, magenta_person_rgb

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.spatial import FramingLabel
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.chromatics import ChromaticComputeResult, ChromaticFrame
from cine_analyzer.ports.shots import DecodedSample, DetectionResult


class _Detector:
    def detect(self, path: object, config: object, *, duration_ms: int) -> DetectionResult:
        assert duration_ms > 0
        assert config is not None
        assert path is not None
        return DetectionResult(boundaries=(), debug_stats=None)


class _Extractor:
    def __init__(self, jpeg: bytes) -> None:
        self.jpeg = jpeg

    def extract(
        self,
        path: object,
        requests: tuple[object, ...],
        ranges: object,
        *,
        rotation_degrees: int,
    ) -> tuple[DecodedSample, ...]:
        assert path is not None
        assert ranges is not None
        assert rotation_degrees == 0
        return tuple(
            DecodedSample(
                sample_id=request.sample_id,  # type: ignore[attr-defined]
                requested_ms=request.requested_ms,  # type: ignore[attr-defined]
                decoded_ms=request.requested_ms,  # type: ignore[attr-defined]
                frame_index=0,
                jpeg=self.jpeg,
                unavailable_reason=None,
            )
            for request in requests
        )


class _Analyzer:
    def analyze_shot(
        self,
        frames: tuple[ChromaticFrame, ...],
        config: object,
    ) -> ChromaticComputeResult:
        assert frames
        assert config is not None
        return ChromaticComputeResult(
            status=MetricStatus.OK,
            value=make_ok_chromatic().value,
            confidence=0.6,
            reason_code=None,
            evidence_sample_ids=(SAMPLE_ID,),
        )


def test_fake_report_stage_persists_overlays(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    config = tiny_config()
    config = config.model_copy(
        update={"spatial": config.spatial.model_copy(update={"backend": "fake"})}
    )
    analysis = (
        CreateAnalysis(repo).execute(video=video, config=config, request_id="req-phase-06").analysis
    )
    jpeg = encode_jpeg(magenta_person_rgb())
    sampling = RunSamplingStages(store, _Detector(), _Extractor(jpeg), repo)
    result = make_run_report_stages(sampling, store, _Analyzer(), fake_analyzer(), repo).execute(
        video=video,
        analysis=analysis,
        config=config,
        request_id="req-phase-06",
    )
    assert result.report.availability.spatial is StageAvailability.COMPLETE
    assert result.report.shots[0].spatial.status is MetricStatus.OK
    assert result.report.shots[0].spatial.value is not None
    assert result.report.shots[0].spatial.value.framing is FramingLabel.MEDIUM_ESTIMATE
    assert store.contains(result.spatial_key)
    overlay_kinds = [ref.kind for ref, _key in repo.artifacts]
    assert "spatial_overlay" in overlay_kinds
    assert "scene" not in result.report.model_dump_json()
