"""Report-stage motion flag and audio extract degradation."""

from pathlib import Path

from tests.factories import SAMPLE_ID, make_ok_chromatic
from tests.unit.application.fakes import (
    FakeRepository,
    MemoryStore,
    tiny_config,
    video_record_from_bytes,
)
from tests.unit.chromatic.jpeg_util import encode_jpeg, solid_rgb
from tests.unit.spatial.helpers import fake_analyzer

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.application.report import RunReportStages
from cine_analyzer.domain.config import MotionConfig
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.audio import AudioAnalyzeResult
from cine_analyzer.ports.chromatics import ChromaticComputeResult, ChromaticFrame
from cine_analyzer.ports.ingestion import VideoRecord
from cine_analyzer.ports.motion import FlowPairStats, MotionPairInput
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


class _Chroma:
    def analyze_shot(
        self, frames: tuple[ChromaticFrame, ...], config: object
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


class _FlagMotion:
    def analyze_pair(self, pair: MotionPairInput, config: MotionConfig) -> FlowPairStats:
        assert config.working_max_side > 0
        return FlowPairStats(
            sample_id_a=pair.sample_id_a,
            sample_id_b=pair.sample_id_b,
            dt_ms=pair.dt_ms,
            at_ms=pair.at_ms,
            global_dx=8.0,
            global_dy=0.0,
            global_magnitude=3.0,
            residual_magnitude_median=0.1,
            residual_magnitude_p90=0.2,
            valid_ratio=0.9,
            flagged_discontinuity=True,
        )


class _SilentAudio:
    def analyze(self, source: object, **_kwargs: object) -> AudioAnalyzeResult:
        assert source is not None
        return AudioAnalyzeResult(
            status=MetricStatus.FAILED,
            reason_code="audio_extract_failed",
            windows=(None, None),
        )


class _NoneMotion:
    def analyze_pair(self, pair: MotionPairInput, config: MotionConfig) -> None:
        assert pair.dt_ms > 0
        assert config.working_max_side > 0


def test_flagged_flow_is_stored_as_a_timeline_warning(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    analysis = (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id="req-phase-07")
        .analysis
    )
    jpeg = encode_jpeg(solid_rgb((40, 40, 40), size=64))
    sampling = RunSamplingStages(store, _Detector(), _Extractor(jpeg), repo)
    result = RunReportStages(
        sampling,
        store,
        _Chroma(),
        fake_analyzer(),
        _FlagMotion(),
        _SilentAudio(),
        repo,
    ).execute(
        video=video,
        analysis=analysis,
        config=tiny_config(),
        request_id="req-phase-07",
    )
    assert result.report.availability.audio is StageAvailability.UNAVAILABLE
    timeline = store.blobs[result.timeline_key]
    assert b"cut_like_flow_discontinuity" in timeline
    assert b"audio_extract_failed" in timeline


def test_has_audio_true_still_degrades_when_extract_fails(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    metadata = video.metadata.model_copy(update={"has_audio": True, "audio_codec": "aac"})
    video = VideoRecord(
        metadata=metadata,
        original_storage_key=video.original_storage_key,
        probe_storage_key=video.probe_storage_key,
    )
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    analysis = (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id="req-phase-07")
        .analysis
    )
    jpeg = encode_jpeg(solid_rgb((80, 80, 80), size=48))
    sampling = RunSamplingStages(store, _Detector(), _Extractor(jpeg), repo)
    result = RunReportStages(
        sampling,
        store,
        _Chroma(),
        fake_analyzer(),
        _FlagMotion(),
        _SilentAudio(),
        repo,
    ).execute(
        video=video,
        analysis=analysis,
        config=tiny_config(),
        request_id="req-phase-07",
    )
    assert result.report.availability.audio is StageAvailability.UNAVAILABLE
    assert result.report.availability.tension is StageAvailability.COMPLETE


def test_unusable_flow_pairs_still_build_a_timeline(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip-bytes")
    store.put_bytes(b"clip-bytes", storage_key=video.original_storage_key)
    analysis = (
        CreateAnalysis(repo)
        .execute(video=video, config=tiny_config(), request_id="req-phase-07")
        .analysis
    )
    jpeg = encode_jpeg(solid_rgb((80, 80, 80), size=48))
    sampling = RunSamplingStages(store, _Detector(), _Extractor(jpeg), repo)
    result = RunReportStages(
        sampling,
        store,
        _Chroma(),
        fake_analyzer(),
        _NoneMotion(),
        _SilentAudio(),
        repo,
    ).execute(
        video=video,
        analysis=analysis,
        config=tiny_config(),
        request_id="req-phase-07",
    )
    assert result.report.availability.motion is StageAvailability.UNAVAILABLE
    assert result.report.availability.tension is StageAvailability.COMPLETE
    assert b"motion_unavailable_weights_renormalized" in store.blobs[result.timeline_key]
