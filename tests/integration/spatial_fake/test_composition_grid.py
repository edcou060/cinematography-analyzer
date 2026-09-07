"""Fake spatial backend on composition_grid.mp4."""

import json
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
from cine_analyzer.domain.spatial import FramingLabel
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.settings import Settings


def test_composition_grid_fake_spatial_is_a_medium_estimate(
    tmp_path: Path,
    video_fixtures: Path,
) -> None:
    settings = Settings(artifact_root=tmp_path / "artifacts", state_path=tmp_path / "state.sqlite")
    store = FilesystemArtifactStore(settings.artifact_root)
    repo = SqliteAnalysisRepository(settings.state_path)
    base = AnalysisConfig()
    config = base.model_copy(
        update={"spatial": base.spatial.model_copy(update={"backend": "fake"})}
    )
    sampling = RunSamplingStages(
        store,
        PySceneDetectShotDetector(),
        PyAvSampleExtractor(),
        repo,
    )
    reports = make_run_report_stages(
        sampling,
        store,
        OpenCvChromaticAnalyzer(),
        fake_analyzer(),
        repo,
    )
    ingest = IngestVideo(
        store,
        FfprobeMediaProbe(settings.ffprobe_binary, timeout_ms=settings.ffprobe_timeout_ms),
        repo,
        chunk_bytes=settings.ingest_chunk_bytes,
    )
    try:
        video = ingest.execute(
            video_fixtures / "composition_grid.mp4",
            original_filename="composition_grid.mp4",
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
    assert first.report.summary.shot_count == 1
    assert first.report.availability.spatial is StageAvailability.COMPLETE
    spatial = first.report.shots[0].spatial
    assert spatial.status is MetricStatus.OK
    assert spatial.value is not None
    assert spatial.value.framing is FramingLabel.MEDIUM_ESTIMATE
    assert spatial.value.thirds_proximity_score > 0.5
    assert spatial.value.center_proximity_score < spatial.value.thirds_proximity_score
    assert first.report.shots[0].spatial.value == second.report.shots[0].spatial.value
    payload = first.report.model_dump_json()
    assert "scene" not in payload
    assert "thirds_proximity" in payload
    spatial_doc = json.loads(store.local_path(first.spatial_key).read_text(encoding="utf-8"))
    overlay_key = spatial_doc["shots"][0]["overlays"][0]["storage_key"]
    overlay = store.local_path(overlay_key).read_bytes()
    assert overlay[:2] == b"\xff\xd8"
