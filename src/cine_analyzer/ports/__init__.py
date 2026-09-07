"""Ports package. Protocols live beside adapters; domain models do not import them."""

from cine_analyzer.ports.audio import AudioAnalyzer, AudioAnalyzeResult
from cine_analyzer.ports.chromatics import (
    ChromaticAnalyzer,
    ChromaticComputeResult,
    ChromaticFrame,
)
from cine_analyzer.ports.ingestion import (
    AnalysisRecord,
    AnalysisRepository,
    ArtifactStore,
    MediaProbe,
    ProbeFacts,
    StagingObject,
    StoredBlob,
    VideoRecord,
)
from cine_analyzer.ports.motion import (
    FlowPairStats,
    MotionAnalyzer,
    MotionFrame,
    MotionPairInput,
)
from cine_analyzer.ports.shots import (
    DecodedSample,
    DetectedBoundary,
    DetectionResult,
    SampleExtractor,
    ShotDetector,
)
from cine_analyzer.ports.spatial import (
    DetectionHit,
    OverlayRenderer,
    PrimarySubjectSelector,
    SpatialAnalyzer,
    SpatialComputeResult,
    SpatialFrame,
    SubjectDetector,
    SubjectTracker,
)

__all__ = [
    "AnalysisRecord",
    "AnalysisRepository",
    "ArtifactStore",
    "AudioAnalyzeResult",
    "AudioAnalyzer",
    "ChromaticAnalyzer",
    "ChromaticComputeResult",
    "ChromaticFrame",
    "DecodedSample",
    "DetectedBoundary",
    "DetectionHit",
    "DetectionResult",
    "FlowPairStats",
    "MediaProbe",
    "MotionAnalyzer",
    "MotionFrame",
    "MotionPairInput",
    "OverlayRenderer",
    "PrimarySubjectSelector",
    "ProbeFacts",
    "SampleExtractor",
    "ShotDetector",
    "SpatialAnalyzer",
    "SpatialComputeResult",
    "SpatialFrame",
    "StagingObject",
    "StoredBlob",
    "SubjectDetector",
    "SubjectTracker",
    "VideoRecord",
]
