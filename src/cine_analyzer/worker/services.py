"""Worker process wiring. CV adapters load here, never in the API process."""

from dataclasses import dataclass

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.adapters.media.ffmpeg_audio import FfmpegAudioExtractor
from cine_analyzer.adapters.media.pyav_extract import PyAvSampleExtractor
from cine_analyzer.adapters.vision.fake_subject import FakeSubjectDetector
from cine_analyzer.adapters.vision.opencv_chromatics import OpenCvChromaticAnalyzer
from cine_analyzer.adapters.vision.opencv_motion import OpenCvMotionAnalyzer
from cine_analyzer.adapters.vision.opencv_overlay import OpenCvOverlayRenderer
from cine_analyzer.adapters.vision.pyscenedetect import PySceneDetectShotDetector
from cine_analyzer.application.pipeline import RunSamplingStages
from cine_analyzer.application.report import RunReportStages
from cine_analyzer.application.spatial import SpatialShotAnalyzer
from cine_analyzer.application.spatial_select import CoverageAreaConfidenceSelector
from cine_analyzer.application.spatial_track import IoUSubjectTracker
from cine_analyzer.ports.control import JobRepository
from cine_analyzer.ports.ingestion import ArtifactStore
from cine_analyzer.settings import Settings

__all__ = ["WorkerServices", "build_worker_services"]


@dataclass(frozen=True, slots=True)
class WorkerServices:
    """Sampling and report entry points sharing the PostgreSQL repository."""

    store: ArtifactStore
    sampling: RunSamplingStages
    report: RunReportStages


def build_worker_services(settings: Settings, repository: JobRepository) -> WorkerServices:
    """Construct the local pipeline against the control-plane repository."""
    store = FilesystemArtifactStore(settings.artifact_root)
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
    return WorkerServices(
        store=store,
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
    )
