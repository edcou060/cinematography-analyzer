"""Real detector and extractor against generated clips."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tests.unit.application.fakes import REQUEST_ID, FakeRepository

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.adapters.media.pyav_extract import PyAvSampleExtractor
from cine_analyzer.adapters.vision.pyscenedetect import PySceneDetectShotDetector
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.ingest import IngestVideo
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.application.sampling import plan_samples
from cine_analyzer.application.shots import boundaries_to_shot_set, shot_provenance
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.media import SamplePurpose, SampleRequest, SampleStatus
from cine_analyzer.domain.shots import TransitionKind
from cine_analyzer.domain.time import TimeRangeMs


def test_hard_cut_is_detected_near_two_seconds(video_fixtures: Path) -> None:
    result = PySceneDetectShotDetector().detect(
        video_fixtures / "two_color_cut.mp4",
        AnalysisConfig().shots,
        duration_ms=4000,
    )
    assert result.boundaries
    assert all(item.transition is TransitionKind.CUT for item in result.boundaries)
    assert any(abs(item.position_ms - 2000) <= 200 for item in result.boundaries)
    assert all("scene" not in item.transition.name.lower() for item in result.boundaries)


def test_no_cut_clip_has_no_internal_boundary(video_fixtures: Path) -> None:
    result = PySceneDetectShotDetector().detect(
        video_fixtures / "no_cut.mp4",
        AnalysisConfig().shots,
        duration_ms=4000,
    )
    assert result.boundaries == ()


def test_extraction_records_requested_and_decoded_timestamps(video_fixtures: Path) -> None:
    shot_id = uuid4()
    sample_id = uuid4()
    request = SampleRequest(
        sample_id=sample_id,
        shot_id=shot_id,
        requested_ms=1000,
        purposes=(SamplePurpose.EVIDENCE,),
    )
    results = PyAvSampleExtractor().extract(
        video_fixtures / "two_color_cut.mp4",
        (request,),
        {shot_id: TimeRangeMs(start_ms=0, end_ms=2000)},
        rotation_degrees=0,
    )
    assert len(results) == 1
    decoded = results[0]
    assert decoded.requested_ms == 1000
    assert decoded.decoded_ms is not None
    assert decoded.decoded_ms >= 1000
    assert decoded.decoded_ms < 2000
    assert decoded.jpeg is not None
    assert decoded.jpeg[:2] == b"\xff\xd8"


def test_a_request_that_can_only_be_filled_from_another_shot_is_unavailable(
    video_fixtures: Path,
) -> None:
    shot_id = uuid4()
    results = PyAvSampleExtractor().extract(
        video_fixtures / "two_color_cut.mp4",
        (
            SampleRequest(
                sample_id=uuid4(),
                shot_id=shot_id,
                requested_ms=1500,
                purposes=(SamplePurpose.EVIDENCE,),
            ),
        ),
        {shot_id: TimeRangeMs(start_ms=0, end_ms=1000)},
        rotation_degrees=0,
    )
    assert results[0].jpeg is None
    assert results[0].decoded_ms is None
    assert results[0].unavailable_reason == "decoded timestamp is outside the requested shot"


def test_sampling_pipeline_covers_the_clip_exactly(tmp_path: Path, video_fixtures: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    repo = FakeRepository()
    ingest = IngestVideo(
        store,
        FfprobeMediaProbe("ffprobe", timeout_ms=15_000),
        repo,
        chunk_bytes=65_536,
    )
    ingested = ingest.execute(
        video_fixtures / "two_color_cut.mp4",
        original_filename="two_color_cut.mp4",
        config=AnalysisConfig(),
        request_id=REQUEST_ID,
    )
    analysis = CreateAnalysis(repo).execute(
        video=ingested.video,
        config=AnalysisConfig(),
        request_id=REQUEST_ID,
    )
    result = RunSamplingStages(
        store,
        PySceneDetectShotDetector(),
        PyAvSampleExtractor(),
        repo,
    ).execute(
        video=ingested.video,
        analysis=analysis.analysis,
        config=AnalysisConfig(),
        request_id=REQUEST_ID,
    )
    duration_ms = ingested.video.metadata.duration_ms
    assert result.shot_set.shots[0].time_range.start_ms == 0
    assert result.shot_set.shots[-1].time_range.end_ms == duration_ms
    assert result.shot_set.duration_ms() == duration_ms
    assert all(
        left.time_range.end_ms == right.time_range.start_ms
        for left, right in zip(result.shot_set.shots, result.shot_set.shots[1:], strict=False)
    )
    decoded = [item for item in result.manifest.results if item.status is SampleStatus.DECODED]
    assert decoded
    for item in decoded:
        assert item.decoded_ms is not None
        assert item.requested_ms >= 0
        assert item.image is not None
        assert item.sample_id in result.sample_keys
        jpeg = b"".join(store.open_read(result.sample_keys[item.sample_id]))
        assert jpeg[:2] == b"\xff\xd8"
    assert store.contains(result.shot_set_key)
    assert store.contains(result.manifest_key)
    plan = plan_samples(
        result.shot_set,
        video_id=ingested.video.metadata.video_id,
        config=AnalysisConfig(),
        frame_rate=ingested.video.metadata.average_frame_rate,
    )
    assert [request.sample_id for request in plan.requests] == [
        request.sample_id for request in result.plan.requests
    ]
    stamp = datetime.now(tz=UTC)
    rebuilt = boundaries_to_shot_set(
        (),
        analysis_id=analysis.analysis.analysis_id,
        duration_ms=duration_ms,
        min_shot_ms=300,
        provenance=shot_provenance(
            config_hash=AnalysisConfig().hash(),
            code_revision="test",
            method="shots.pyscenedetect.adaptive",
            started_at=stamp,
            completed_at=stamp,
        ),
    )
    assert len(rebuilt.shots) == 1
    assert rebuilt.shots[0].time_range.end_ms == duration_ms
