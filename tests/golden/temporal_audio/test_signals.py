"""Golden temporal/audio signals: known cut, beeps, and motion events."""

import math
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
from cine_analyzer.application.report import ReportStageResult
from cine_analyzer.application.timeline import summarize_timeline
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import SCHEMA_VERSION
from cine_analyzer.settings import Settings


def _run(tmp_path: Path, clip: Path) -> tuple[ReportStageResult, FilesystemArtifactStore]:
    settings = Settings(artifact_root=tmp_path / "artifacts", state_path=tmp_path / "state.sqlite")
    store = FilesystemArtifactStore(settings.artifact_root)
    repo = SqliteAnalysisRepository(settings.state_path)
    config = AnalysisConfig()
    sampling = RunSamplingStages(store, PySceneDetectShotDetector(), PyAvSampleExtractor(), repo)
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
            clip, original_filename=clip.name, config=config, request_id=REQUEST_ID
        ).video
        analysis = (
            CreateAnalysis(repo).execute(video=video, config=config, request_id=REQUEST_ID).analysis
        )
        result = reports.execute(
            video=video, analysis=analysis, config=config, request_id=REQUEST_ID
        )
    finally:
        repo.close()
    return result, store


def test_tension_signals_peak_near_known_events(tmp_path: Path, video_fixtures: Path) -> None:
    result, store = _run(tmp_path, video_fixtures / "tension_signals.mp4")
    report = result.report
    assert report.availability.audio is StageAvailability.COMPLETE
    assert report.availability.tension is StageAvailability.COMPLETE
    assert report.timeline_artifact is not None
    assert report.video.has_audio is True
    timeline = Timeline.model_validate_json(store.local_path(result.timeline_key).read_bytes())
    assert timeline.schema_version == SCHEMA_VERSION
    for point in timeline.points:
        tension = point.tension
        for value in (
            tension.cut_activity,
            tension.audio_activity,
            tension.motion_activity,
            tension.combined_proxy,
        ):
            assert 0.0 <= value <= 1.0
            assert math.isfinite(value)
    cut_peak = max(timeline.points, key=lambda item: item.tension.cut_activity)
    assert abs(cut_peak.at_ms - 2000) <= 500
    audio_ranked = sorted(
        timeline.points, key=lambda item: item.tension.audio_activity, reverse=True
    )
    audio_times = {item.at_ms for item in audio_ranked[:3]}
    assert any(abs(item - 1000) <= 500 for item in audio_times)
    assert any(abs(item - 3000) <= 500 for item in audio_times)
    first_half = [item for item in timeline.points if item.at_ms < 2000]
    second_half = [item for item in timeline.points if item.at_ms >= 2000]
    assert first_half
    assert second_half
    assert max(item.tension.motion_activity for item in first_half) >= 0.0
    summary = summarize_timeline(timeline)
    assert summary["label"] == "tension proxy"
    timeline_dump = timeline.model_dump_json()
    assert "combined_proxy" in timeline_dump
    dumped = report.model_dump_json()
    assert "emotion" not in dumped.lower()
    assert "emotion" not in timeline_dump.lower()
    assert "scene" not in dumped
    assert "scene" not in timeline_dump


def test_no_audio_clip_renormalizes_and_does_not_invent_silence(
    tmp_path: Path, video_fixtures: Path
) -> None:
    result, store = _run(tmp_path, video_fixtures / "no_audio.mp4")
    report = result.report
    assert report.video.has_audio is False
    assert report.availability.audio is StageAvailability.UNAVAILABLE
    assert report.availability.tension is StageAvailability.COMPLETE
    timeline = Timeline.model_validate_json(store.local_path(result.timeline_key).read_bytes())
    assert "no_audio_stream" in timeline.warnings
    assert "audio_unavailable_weights_renormalized" in timeline.warnings
    assert all(point.audio is None for point in timeline.points)
    assert all(point.tension.audio_activity == 0.0 for point in timeline.points)
    assert timeline.effective_weights.audio_activity == 0.0
    remaining = timeline.effective_weights.cut_activity + timeline.effective_weights.motion
    assert abs(remaining - 1.0) < 1e-9
