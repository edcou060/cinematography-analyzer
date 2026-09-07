"""Run shot detection, sampling, and evidence extraction for one analysis."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from cine_analyzer import __version__
from cine_analyzer.application.errors import AdapterError, wrap_adapter
from cine_analyzer.application.ingest import content_storage_key
from cine_analyzer.application.sampling import SAMPLING_METHOD_VERSION, plan_samples
from cine_analyzer.application.shots import boundaries_to_shot_set, shot_provenance
from cine_analyzer.application.stage_execute import tick_cancel
from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
)
from cine_analyzer.domain.shots import ShotSet
from cine_analyzer.domain.types import SCHEMA_VERSION
from cine_analyzer.logging_setup import bind_context, get_logger
from cine_analyzer.ports.ingestion import (
    AnalysisRecord,
    AnalysisRepository,
    ArtifactStore,
    StoredBlob,
    VideoRecord,
)
from cine_analyzer.ports.shots import DecodedSample, SampleExtractor, ShotDetector

__all__ = ["RunSamplingStages", "SamplingStageResult"]


@dataclass(frozen=True, slots=True)
class SamplingStageResult:
    """Shot set, plan, extract outcomes, and replaceable stage artifact keys."""

    shot_set: ShotSet
    plan: SamplingPlan
    manifest: SamplingManifest
    shot_set_key: str
    manifest_key: str
    debug_stats_key: str | None
    sample_keys: dict[UUID, str]


class RunSamplingStages:
    """Local sequential decode slice: shots then sampling. No chromatics."""

    def __init__(
        self,
        store: ArtifactStore,
        detector: ShotDetector,
        extractor: SampleExtractor,
        repository: AnalysisRepository,
    ) -> None:
        self._store = store
        self._detector = detector
        self._extractor = extractor
        self._repository = repository

    def execute(
        self,
        *,
        video: VideoRecord,
        analysis: AnalysisRecord,
        config: AnalysisConfig,
        request_id: str,
        cancel_check: Callable[[], None] | None = None,
    ) -> SamplingStageResult:
        """Detect shots, plan samples, extract evidence, and persist stage artifacts."""
        with bind_context(
            request_id=request_id,
            video_id=str(video.metadata.video_id),
            analysis_id=str(analysis.analysis_id),
            stage="sampling",
        ):
            try:
                result = self._execute(
                    video=video,
                    analysis=analysis,
                    config=config,
                    cancel_check=cancel_check,
                )
            except AdapterError as error:
                raise wrap_adapter(error, request_id=request_id) from error
            get_logger(__name__).info(
                "sampling.completed",
                shot_count=len(result.shot_set.shots),
                sample_count=len(result.plan.requests),
            )
            return result

    def _execute(
        self,
        *,
        video: VideoRecord,
        analysis: AnalysisRecord,
        config: AnalysisConfig,
        cancel_check: Callable[[], None] | None = None,
    ) -> SamplingStageResult:
        source = self._store.local_path(video.original_storage_key)
        started = datetime.now(tz=UTC)
        detected = self._detector.detect(
            source,
            config.shots,
            duration_ms=video.metadata.duration_ms,
        )
        tick_cancel(cancel_check)
        completed = datetime.now(tz=UTC)
        provenance = shot_provenance(
            config_hash=config.hash(),
            code_revision=f"cine-analyzer-{__version__}",
            method=f"shots.{config.shots.backend}.{config.shots.detector}",
            started_at=started,
            completed_at=completed,
        )
        shot_set = boundaries_to_shot_set(
            detected.boundaries,
            analysis_id=analysis.analysis_id,
            duration_ms=video.metadata.duration_ms,
            min_shot_ms=config.shots.min_shot_ms,
            provenance=provenance,
        )
        plan = plan_samples(
            shot_set,
            video_id=video.metadata.video_id,
            config=config,
            frame_rate=video.metadata.average_frame_rate,
        )
        ranges = {shot.shot_id: shot.time_range for shot in shot_set.shots}
        extracted = self._extractor.extract(
            source,
            plan.requests,
            ranges,
            rotation_degrees=video.metadata.display_rotation_degrees,
        )
        tick_cancel(cancel_check)
        sample_keys, results = self._store_samples(
            plan=plan, extracted=extracted, cancel_check=cancel_check
        )
        shot_set = _with_representatives(shot_set, plan)
        prefix = f"analyses/{analysis.analysis_id.hex}"
        shot_blob = self._store.put_replaceable(
            shot_set.model_dump_json().encode("utf-8"),
            storage_key=f"{prefix}/shot_set.json",
        )
        manifest = SamplingManifest(
            schema_version=SCHEMA_VERSION,
            analysis_id=analysis.analysis_id,
            video_id=video.metadata.video_id,
            method_version=SAMPLING_METHOD_VERSION,
            plan=plan,
            results=results,
        )
        manifest_blob = self._store.put_replaceable(
            manifest.model_dump_json().encode("utf-8"),
            storage_key=f"{prefix}/sampling_manifest.json",
        )
        debug_key: str | None = None
        if detected.debug_stats is not None:
            debug_blob = self._store.put_replaceable(
                detected.debug_stats,
                storage_key=f"{prefix}/detector_stats.csv",
            )
            self._record_blob(debug_blob, kind="detector_stats", media_type="text/csv")
            debug_key = debug_blob.storage_key
        self._record_blob(shot_blob, kind="shot_set", media_type="application/json")
        self._record_blob(manifest_blob, kind="sampling_manifest", media_type="application/json")
        return SamplingStageResult(
            shot_set=shot_set,
            plan=plan,
            manifest=manifest,
            shot_set_key=shot_blob.storage_key,
            manifest_key=manifest_blob.storage_key,
            debug_stats_key=debug_key,
            sample_keys=sample_keys,
        )

    def _store_samples(
        self,
        *,
        plan: SamplingPlan,
        extracted: tuple[DecodedSample, ...],
        cancel_check: Callable[[], None] | None = None,
    ) -> tuple[dict[UUID, str], tuple[SampleResult, ...]]:
        by_id = {item.sample_id: item for item in extracted}
        sample_keys: dict[UUID, str] = {}
        results: list[SampleResult] = []
        for request in plan.requests:
            tick_cancel(cancel_check)
            decoded = by_id.get(request.sample_id)
            if decoded is None or decoded.jpeg is None or decoded.decoded_ms is None:
                reason = "sample could not be decoded"
                if decoded is not None and decoded.unavailable_reason is not None:
                    reason = decoded.unavailable_reason
                results.append(
                    SampleResult(
                        sample_id=request.sample_id,
                        shot_id=request.shot_id,
                        requested_ms=request.requested_ms,
                        purposes=request.purposes,
                        status=SampleStatus.UNAVAILABLE,
                        unavailable_reason=reason,
                    )
                )
                continue
            digest_blob = self._store.put_bytes(
                decoded.jpeg,
                storage_key=content_storage_key(sha256(decoded.jpeg).hexdigest()),
            )
            sample_keys[request.sample_id] = digest_blob.storage_key
            image = ArtifactRef(
                artifact_id=uuid4(),
                kind="evidence_frame",
                media_type="image/jpeg",
                sha256=digest_blob.sha256,
                size_bytes=digest_blob.size_bytes,
                schema_version=None,
            )
            self._repository.insert_artifact(image, storage_key=digest_blob.storage_key)
            results.append(
                SampleResult(
                    sample_id=request.sample_id,
                    shot_id=request.shot_id,
                    requested_ms=request.requested_ms,
                    decoded_ms=decoded.decoded_ms,
                    frame_index=decoded.frame_index,
                    purposes=request.purposes,
                    status=SampleStatus.DECODED,
                    image=image,
                )
            )
        return sample_keys, tuple(results)

    def _record_blob(self, blob: StoredBlob, *, kind: str, media_type: str) -> None:
        self._repository.insert_artifact(
            ArtifactRef(
                artifact_id=uuid4(),
                kind=kind,
                media_type=media_type,
                sha256=blob.sha256,
                size_bytes=blob.size_bytes,
                schema_version=SCHEMA_VERSION,
            ),
            storage_key=blob.storage_key,
        )


def _with_representatives(shot_set: ShotSet, plan: SamplingPlan) -> ShotSet:
    evidence: dict[UUID, UUID] = {}
    for request in plan.requests:
        if SamplePurpose.EVIDENCE in request.purposes:
            evidence[request.shot_id] = request.sample_id
    return shot_set.model_copy(
        update={
            "shots": tuple(
                shot.model_copy(update={"representative_sample_id": evidence.get(shot.shot_id)})
                for shot in shot_set.shots
            )
        }
    )
