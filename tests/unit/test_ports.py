"""Ports package re-exports the ingestion protocols."""

from cine_analyzer.ports import (
    AnalysisRecord,
    AnalysisRepository,
    ArtifactStore,
    ChromaticAnalyzer,
    ChromaticComputeResult,
    ChromaticFrame,
    DecodedSample,
    DetectedBoundary,
    DetectionHit,
    DetectionResult,
    MediaProbe,
    OverlayRenderer,
    PrimarySubjectSelector,
    ProbeFacts,
    SampleExtractor,
    ShotDetector,
    SpatialAnalyzer,
    SpatialComputeResult,
    SpatialFrame,
    StagingObject,
    StoredBlob,
    SubjectDetector,
    SubjectTracker,
    VideoRecord,
)


def test_ports_package_re_exports_ingestion_types() -> None:
    assert ArtifactStore is not None
    assert MediaProbe is not None
    assert AnalysisRepository is not None
    assert StagingObject is not None
    assert StoredBlob is not None
    assert ProbeFacts is not None
    assert VideoRecord is not None
    assert AnalysisRecord is not None


def test_ports_package_re_exports_shot_types() -> None:
    assert ShotDetector is not None
    assert SampleExtractor is not None
    assert DetectedBoundary is not None
    assert DetectionResult is not None
    assert DecodedSample is not None


def test_ports_package_re_exports_chromatic_types() -> None:
    assert ChromaticAnalyzer is not None
    assert ChromaticFrame is not None
    assert ChromaticComputeResult is not None


def test_ports_package_re_exports_spatial_types() -> None:
    assert DetectionHit is not None
    assert OverlayRenderer is not None
    assert PrimarySubjectSelector is not None
    assert SpatialAnalyzer is not None
    assert SpatialComputeResult is not None
    assert SpatialFrame is not None
    assert SubjectDetector is not None
    assert SubjectTracker is not None
