"""Framework-independent domain contracts.

Importing this package loads none of the infrastructure adapters and performs no I/O.
"""

from cine_analyzer.domain.artifacts import ArtifactRef, EvidenceFrame, MethodProvenance
from cine_analyzer.domain.chromatics import (
    ChromaticMeasurement,
    ChromaticValue,
    ColorSwatch,
    LabColor,
    LightingKeyLabel,
    LightnessDistribution,
    RgbColor,
)
from cine_analyzer.domain.config import AnalysisConfig, canonical_hash
from cine_analyzer.domain.errors import ErrorPrefix, SafeError, retry_class_for
from cine_analyzer.domain.jobs import (
    AnalysisState,
    AnalysisStatusResponse,
    IllegalStateTransitionError,
    StageCommand,
    StageResult,
    StageState,
    is_partial_outcome,
    transition_analysis,
    transition_stage,
)
from cine_analyzer.domain.measurements import Measurement
from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleRequest,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
    VideoMetadata,
)
from cine_analyzer.domain.report import (
    AnalysisReport,
    Critique,
    ReportAvailability,
    ShotAnalysis,
    StageAvailability,
    VideoSummary,
)
from cine_analyzer.domain.shots import Shot, ShotBoundary, ShotSet, TransitionKind
from cine_analyzer.domain.spatial import (
    BoxNorm,
    FramingLabel,
    SpatialMeasurement,
    SpatialValue,
    SubjectObservation,
)
from cine_analyzer.domain.temporal import (
    AudioWindowValue,
    TemporalMeasurement,
    TemporalValue,
    TensionComponents,
)
from cine_analyzer.domain.time import Rational, TimeRangeMs
from cine_analyzer.domain.timeline import Timeline, TimelinePoint
from cine_analyzer.domain.types import MetricStatus, StrictModel

__all__ = [
    "AnalysisConfig",
    "AnalysisReport",
    "AnalysisState",
    "AnalysisStatusResponse",
    "ArtifactRef",
    "AudioWindowValue",
    "BoxNorm",
    "ChromaticMeasurement",
    "ChromaticValue",
    "ColorSwatch",
    "Critique",
    "ErrorPrefix",
    "EvidenceFrame",
    "FramingLabel",
    "IllegalStateTransitionError",
    "LabColor",
    "LightingKeyLabel",
    "LightnessDistribution",
    "Measurement",
    "MethodProvenance",
    "MetricStatus",
    "Rational",
    "ReportAvailability",
    "RgbColor",
    "SafeError",
    "SamplePurpose",
    "SampleRequest",
    "SampleResult",
    "SampleStatus",
    "SamplingManifest",
    "SamplingPlan",
    "Shot",
    "ShotAnalysis",
    "ShotBoundary",
    "ShotSet",
    "SpatialMeasurement",
    "SpatialValue",
    "StageAvailability",
    "StageCommand",
    "StageResult",
    "StageState",
    "StrictModel",
    "SubjectObservation",
    "TemporalMeasurement",
    "TemporalValue",
    "TensionComponents",
    "TimeRangeMs",
    "Timeline",
    "TimelinePoint",
    "TransitionKind",
    "VideoMetadata",
    "VideoSummary",
    "canonical_hash",
    "is_partial_outcome",
    "retry_class_for",
    "transition_analysis",
    "transition_stage",
]
