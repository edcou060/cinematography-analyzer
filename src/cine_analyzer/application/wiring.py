"""Process-edge construction of ports. Domain code never imports this module."""

from dataclasses import dataclass

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.adapters.media.ffmpeg_audio import FfmpegAudioExtractor
from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.adapters.media.pyav_extract import PyAvSampleExtractor
from cine_analyzer.adapters.persistence.sqlite import SqliteAnalysisRepository
from cine_analyzer.adapters.vision.fake_subject import FakeSubjectDetector
from cine_analyzer.adapters.vision.opencv_chromatics import OpenCvChromaticAnalyzer
from cine_analyzer.adapters.vision.opencv_motion import OpenCvMotionAnalyzer
from cine_analyzer.adapters.vision.opencv_overlay import OpenCvOverlayRenderer
from cine_analyzer.adapters.vision.pyscenedetect import PySceneDetectShotDetector
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.ingest import IngestVideo
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.application.report import RunReportStages
from cine_analyzer.application.spatial import SpatialShotAnalyzer
from cine_analyzer.application.spatial_select import CoverageAreaConfidenceSelector
from cine_analyzer.application.spatial_track import IoUSubjectTracker
from cine_analyzer.settings import Settings

__all__ = ["Services", "build_services"]


@dataclass(frozen=True, slots=True)
class Services:
    """Local ingest/analyze/sampling/report services for the CLI vertical slice."""

    ingest: IngestVideo
    analyze: CreateAnalysis
    sampling: RunSamplingStages
    report: RunReportStages
    repository: SqliteAnalysisRepository


def build_services(settings: Settings) -> Services:
    """Construct filesystem, ffprobe, detector, extractor, chromatic, and SQLite adapters."""
    store = FilesystemArtifactStore(settings.artifact_root)
    probe = FfprobeMediaProbe(
        settings.ffprobe_binary,
        timeout_ms=settings.ffprobe_timeout_ms,
    )
    repository = SqliteAnalysisRepository(settings.state_path)
    sampling = RunSamplingStages(
        store,
        PySceneDetectShotDetector(),
        PyAvSampleExtractor(),
        repository,
    )
    spatial = SpatialShotAnalyzer(
        {"fake": FakeSubjectDetector()},
        IoUSubjectTracker(),
        CoverageAreaConfidenceSelector(),
        OpenCvOverlayRenderer(),
    )
    return Services(
        ingest=IngestVideo(
            store,
            probe,
            repository,
            chunk_bytes=settings.ingest_chunk_bytes,
            min_free_bytes=settings.min_free_bytes,
        ),
        analyze=CreateAnalysis(repository),
        sampling=sampling,
        report=RunReportStages(
            sampling,
            store,
            OpenCvChromaticAnalyzer(),
            spatial,
            OpenCvMotionAnalyzer(),
            FfmpegAudioExtractor(
                settings.ffmpeg_binary,
                timeout_ms=settings.ffmpeg_timeout_ms,
                max_stdout_bytes=settings.ffmpeg_max_stdout_bytes,
            ),
            repository,
        ),
        repository=repository,
    )
