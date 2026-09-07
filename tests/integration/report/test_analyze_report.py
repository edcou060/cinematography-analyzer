"""End-to-end local report: shots, chromatics, validated JSON."""

from pathlib import Path

from tests.unit.application.fakes import REQUEST_ID, make_run_report_stages
from tests.unit.spatial.helpers import fake_analyzer

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.adapters.media.pyav_extract import PyAvSampleExtractor
from cine_analyzer.adapters.persistence.sqlite import SqliteAnalysisRepository
from cine_analyzer.adapters.vision.opencv_chromatics import OpenCvChromaticAnalyzer
from cine_analyzer.adapters.vision.pyscenedetect import PySceneDetectShotDetector
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.ingest import IngestVideo
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.report import AnalysisReport, StageAvailability
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.settings import Settings


def test_two_color_cut_report_validates_and_is_repeatable(
    tmp_path: Path,
    video_fixtures: Path,
) -> None:
    settings = Settings(artifact_root=tmp_path / "artifacts", state_path=tmp_path / "state.sqlite")
    store = FilesystemArtifactStore(settings.artifact_root)
    repo = SqliteAnalysisRepository(settings.state_path)
    config = AnalysisConfig()
    sampling = RunSamplingStages(
        store,
        PySceneDetectShotDetector(),
        PyAvSampleExtractor(),
        repo,
    )
    reports = make_run_report_stages(
        sampling, store, OpenCvChromaticAnalyzer(), fake_analyzer(), repo
    )
    ingest = IngestVideo(
        store,
        FfprobeMediaProbe(settings.ffprobe_binary, timeout_ms=settings.ffprobe_timeout_ms),
        repo,
        chunk_bytes=settings.ingest_chunk_bytes,
    )
    try:
        video = ingest.execute(
            video_fixtures / "two_color_cut.mp4",
            original_filename="two_color_cut.mp4",
            config=config,
            request_id=REQUEST_ID,
        ).video
        analysis = (
            CreateAnalysis(repo).execute(video=video, config=config, request_id=REQUEST_ID).analysis
        )
        first = reports.execute(
            video=video, analysis=analysis, config=config, request_id=REQUEST_ID
        )
        second = reports.execute(
            video=video, analysis=analysis, config=config, request_id=REQUEST_ID
        )
    finally:
        repo.close()

    restored = AnalysisReport.model_validate_json(first.report.model_dump_json())
    assert restored == first.report
    assert first.report.summary.shot_count == 2
    assert first.report.availability.chromatic is StageAvailability.COMPLETE
    assert first.report.availability.spatial is StageAvailability.UNAVAILABLE
    assert all(item.spatial.reason_code == "detector_not_installed" for item in first.report.shots)
    assert all(item.spatial.status is MetricStatus.NOT_COMPUTED for item in first.report.shots)
    assert all(item.chromatic.status is MetricStatus.OK for item in first.report.shots)
    assert "ESTIMATE" in first.report.shots[0].chromatic.value.lighting_key.value  # type: ignore[union-attr]
    assert first.report.shots[0].chromatic.value.palette[0].rgb.r > 80  # type: ignore[union-attr]
    assert first.report.shots[1].chromatic.value.palette[0].rgb.b > 80  # type: ignore[union-attr]
    first_hex = [
        [swatch.rgb.hex for swatch in item.chromatic.value.palette]  # type: ignore[union-attr]
        for item in first.report.shots
    ]
    second_hex = [
        [swatch.rgb.hex for swatch in item.chromatic.value.palette]  # type: ignore[union-attr]
        for item in second.report.shots
    ]
    assert first_hex == second_hex
    assert [item.chromatic.value.lighting_key for item in first.report.shots] == [  # type: ignore[union-attr]
        item.chromatic.value.lighting_key
        for item in second.report.shots  # type: ignore[union-attr]
    ]
    assert "scene" not in first.report.model_dump_json()
