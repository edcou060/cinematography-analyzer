"""Spatial shot analysis: detect, track, select, proximity, framing estimate, overlays."""

from uuid import UUID

from cine_analyzer.application.framing import estimate_framing, framing_confidence
from cine_analyzer.application.sample_frames import load_decoded_jpegs
from cine_analyzer.application.spatial_geometry import (
    box_area,
    box_height,
    center_proximity,
    thirds_proximity,
)
from cine_analyzer.application.spatial_select import CoverageAreaConfidenceSelector, track_coverage
from cine_analyzer.domain.artifacts import MethodProvenance
from cine_analyzer.domain.config import SpatialConfig
from cine_analyzer.domain.media import SamplePurpose, SamplingManifest
from cine_analyzer.domain.spatial import SpatialMeasurement, SpatialValue, SubjectObservation
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.ingestion import ArtifactStore
from cine_analyzer.ports.spatial import (
    OverlayRenderer,
    SpatialComputeResult,
    SpatialFrame,
    SubjectDetector,
    SubjectTracker,
)

__all__ = [
    "SPATIAL_METHOD_VERSION",
    "SpatialShotAnalyzer",
    "collect_spatial_frames",
    "wrap_spatial_measurement",
]

SPATIAL_METHOD_VERSION = "spatial-v1"
_FAKE = "fake"
_NO_DETECTOR = "detector_not_installed"
_NO_SUBJECT = "spatial_no_subject"
_NO_FRAMES = "spatial_no_decoded_samples"


class SpatialShotAnalyzer:
    """CPU spatial pillar. Unknown backends degrade to detector_not_installed."""

    def __init__(
        self,
        detectors: dict[str, SubjectDetector],
        tracker: SubjectTracker,
        selector: CoverageAreaConfidenceSelector,
        overlay: OverlayRenderer,
    ) -> None:
        self._detectors = detectors
        self._tracker = tracker
        self._selector = selector
        self._overlay = overlay

    def analyze_shot(
        self,
        frames: tuple[SpatialFrame, ...],
        config: SpatialConfig,
    ) -> SpatialComputeResult:
        """Run the fake detector path, or abstain when no detector is enabled."""
        if config.backend != _FAKE:
            return _absent(MetricStatus.NOT_COMPUTED, _NO_DETECTOR, (), (), ())
        detector = self._detectors.get(config.backend)
        if detector is None:
            return _absent(MetricStatus.NOT_COMPUTED, _NO_DETECTOR, (), (), ())
        if not frames:
            return _absent(MetricStatus.INSUFFICIENT_DATA, _NO_FRAMES, (), (), ())
        hits = detector.infer(frames, config)
        sample_ids = tuple(frame.sample_id for frame in frames)
        observations = self._tracker.track(hits, sample_ids, config)
        primary = self._selector.select(observations, len(frames), config)
        overlays = _overlays(self._overlay, frames, observations, primary)
        evidence = sample_ids
        if primary is None:
            return SpatialComputeResult(
                status=MetricStatus.NO_SUBJECT,
                value=None,
                confidence=None,
                reason_code=_NO_SUBJECT,
                evidence_sample_ids=evidence,
                observations=observations,
                overlays=overlays,
            )
        members = tuple(item for item in observations if item.track_id == primary)
        coverage = track_coverage(observations, len(frames), primary)
        value = _value(members, primary, coverage, config)
        return SpatialComputeResult(
            status=MetricStatus.OK,
            value=value,
            confidence=value.framing_confidence,
            reason_code=None,
            evidence_sample_ids=evidence,
            observations=observations,
            overlays=overlays,
        )


def collect_spatial_frames(
    manifest: SamplingManifest,
    sample_keys: dict[UUID, str],
    store: ArtifactStore,
    shot_id: UUID,
) -> tuple[SpatialFrame, ...]:
    """Load decoded composition JPEGs for one shot."""
    return tuple(
        SpatialFrame(sample_id=sample_id, jpeg=jpeg)
        for sample_id, jpeg in load_decoded_jpegs(
            manifest, sample_keys, store, shot_id, SamplePurpose.COMPOSITION
        )
    )


def wrap_spatial_measurement(
    computed: SpatialComputeResult,
    *,
    method: MethodProvenance,
) -> SpatialMeasurement:
    """Convert analyzer output into a measurement envelope."""
    if computed.status is MetricStatus.OK:
        return SpatialMeasurement(
            status=MetricStatus.OK,
            value=computed.value,
            confidence=computed.confidence,
            evidence_sample_ids=computed.evidence_sample_ids,
            method=method,
        )
    reason = computed.reason_code if computed.reason_code else "spatial_unavailable"
    return SpatialMeasurement(
        status=computed.status,
        value=None,
        reason_code=reason,
        evidence_sample_ids=computed.evidence_sample_ids,
        method=method,
    )


def _value(
    members: tuple[SubjectObservation, ...],
    track_id: str,
    coverage: float,
    config: SpatialConfig,
) -> SpatialValue:
    areas = [box_area(item.box) for item in members]
    heights = [box_height(item.box) for item in members]
    thirds = [
        thirds_proximity((item.centroid_x, item.centroid_y), config.thirds_sigma)
        for item in members
    ]
    centers = [
        center_proximity((item.centroid_x, item.centroid_y), config.thirds_sigma)
        for item in members
    ]
    framing = estimate_framing(members, config.framing_rules)
    return SpatialValue(
        primary_track_id=track_id,
        subject_coverage_ratio_median=_median(areas),
        subject_height_ratio_median=_median(heights),
        thirds_proximity_score=_median(thirds),
        thirds_proximity_p10=_percentile(thirds, 10.0),
        center_proximity_score=_median(centers),
        framing=framing,
        framing_confidence=framing_confidence(framing, members, config.framing_rules, coverage),
        track_coverage_ratio=coverage,
    )


def _overlays(
    overlay: OverlayRenderer,
    frames: tuple[SpatialFrame, ...],
    observations: tuple[SubjectObservation, ...],
    primary: str | None,
) -> tuple[tuple[UUID, bytes], ...]:
    rendered: list[tuple[UUID, bytes]] = []
    for frame in frames:
        members = tuple(item for item in observations if item.sample_id == frame.sample_id)
        jpeg = overlay.render(frame.jpeg, members, primary)
        if jpeg is not None:
            rendered.append((frame.sample_id, jpeg))
    return tuple(rendered)


def _absent(
    status: MetricStatus,
    reason: str,
    evidence: tuple[UUID, ...],
    observations: tuple[SubjectObservation, ...],
    overlays: tuple[tuple[UUID, bytes], ...],
) -> SpatialComputeResult:
    return SpatialComputeResult(
        status=status,
        value=None,
        confidence=None,
        reason_code=reason,
        evidence_sample_ids=evidence,
        observations=observations,
        overlays=overlays,
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = int(percent / 100.0 * (len(ordered) - 1))
    return ordered[min(len(ordered) - 1, max(0, index))]
