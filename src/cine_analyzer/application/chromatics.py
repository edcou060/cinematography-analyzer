"""Attach provenance to chromatic adapter results and collect shot frames."""

from uuid import UUID

from cine_analyzer.application.lighting_key import CHROMATIC_METHOD_VERSION
from cine_analyzer.application.sample_frames import load_decoded_jpegs
from cine_analyzer.domain.artifacts import MethodProvenance
from cine_analyzer.domain.chromatics import ChromaticMeasurement
from cine_analyzer.domain.media import SamplePurpose, SamplingManifest
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.chromatics import ChromaticComputeResult, ChromaticFrame
from cine_analyzer.ports.ingestion import ArtifactStore

__all__ = [
    "CHROMATIC_METHOD_VERSION",
    "collect_shot_frames",
    "wrap_chromatic_measurement",
]


def collect_shot_frames(
    manifest: SamplingManifest,
    sample_keys: dict[UUID, str],
    store: ArtifactStore,
    shot_id: UUID,
) -> tuple[ChromaticFrame, ...]:
    """Load decoded chromatic JPEGs for one shot in manifest order."""
    return tuple(
        ChromaticFrame(sample_id=sample_id, jpeg=jpeg)
        for sample_id, jpeg in load_decoded_jpegs(
            manifest, sample_keys, store, shot_id, SamplePurpose.CHROMATIC
        )
    )


def wrap_chromatic_measurement(
    computed: ChromaticComputeResult,
    *,
    method: MethodProvenance,
) -> ChromaticMeasurement:
    """Convert adapter output into a measurement envelope."""
    if computed.status is MetricStatus.OK:
        return ChromaticMeasurement(
            status=MetricStatus.OK,
            value=computed.value,
            confidence=computed.confidence,
            evidence_sample_ids=computed.evidence_sample_ids,
            method=method,
        )
    reason = computed.reason_code if computed.reason_code else "chromatic_unavailable"
    return ChromaticMeasurement(
        status=computed.status,
        value=None,
        reason_code=reason,
        evidence_sample_ids=computed.evidence_sample_ids,
        method=method,
    )
