"""Assemble the local AnalysisReport from shots, chromatics, motion, audio, and tension."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from cine_analyzer import __version__
from cine_analyzer.application.chromatics import (
    CHROMATIC_METHOD_VERSION,
    collect_shot_frames,
    wrap_chromatic_measurement,
)
from cine_analyzer.application.errors import AdapterError, wrap_adapter
from cine_analyzer.application.ingest import content_storage_key
from cine_analyzer.application.motion import (
    CUT_LIKE_WARNING,
    MOTION_METHOD_VERSION,
    MotionSeriesPoint,
    adjacent_motion_pairs,
    attach_subject_boxes,
    collect_motion_frames,
    summarize_shot_motion,
)
from cine_analyzer.application.pipeline import RunSamplingStages, SamplingStageResult
from cine_analyzer.application.sample_frames import jpeg_read_cache
from cine_analyzer.application.spatial import (
    SPATIAL_METHOD_VERSION,
    SpatialShotAnalyzer,
    collect_spatial_frames,
    wrap_spatial_measurement,
)
from cine_analyzer.application.stage_execute import tick_cancel
from cine_analyzer.application.timeline import build_timeline, window_starts
from cine_analyzer.domain.artifacts import ArtifactRef, MethodProvenance
from cine_analyzer.domain.chromatics import ChromaticMeasurement
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.report import (
    AnalysisReport,
    ReportAvailability,
    ShotAnalysis,
    StageAvailability,
    VideoSummary,
)
from cine_analyzer.domain.shots import Shot, ShotSet
from cine_analyzer.domain.spatial import SpatialMeasurement, SubjectObservation
from cine_analyzer.domain.temporal import TemporalMeasurement, TemporalValue
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import SCHEMA_VERSION, MetricStatus
from cine_analyzer.logging_setup import bind_context, get_logger
from cine_analyzer.observability.metrics import observe
from cine_analyzer.ports.audio import AudioAnalyzer
from cine_analyzer.ports.chromatics import ChromaticAnalyzer, ChromaticComputeResult
from cine_analyzer.ports.ingestion import (
    AnalysisRecord,
    AnalysisRepository,
    ArtifactStore,
    StoredBlob,
    VideoRecord,
)
from cine_analyzer.ports.motion import FlowPairStats, MotionAnalyzer
from cine_analyzer.ports.spatial import SpatialComputeResult

__all__ = [
    "REPORT_METHOD_VERSION",
    "ReportStageResult",
    "RunReportStages",
    "assemble_report",
    "audio_availability",
    "chromatic_availability",
    "motion_availability",
    "spatial_availability",
    "tension_availability",
    "video_summary",
]

REPORT_METHOD_VERSION = "report-v1"
_TEMPORAL_METHOD_VERSION = "temporal-v1"
_EMPTY_CHROMA = "chromatic_no_decoded_samples"


@dataclass(frozen=True, slots=True)
class ReportStageResult:
    """Sampling outputs plus the validated local report."""

    sampling: SamplingStageResult
    report: AnalysisReport
    report_key: str
    chromatics_key: str
    spatial_key: str
    timeline_key: str


class RunReportStages:
    """Sampling, chromatics, spatial, motion, audio, tension, then a local AnalysisReport."""

    def __init__(
        self,
        sampling: RunSamplingStages,
        store: ArtifactStore,
        analyzer: ChromaticAnalyzer,
        spatial: SpatialShotAnalyzer,
        motion: MotionAnalyzer,
        audio: AudioAnalyzer,
        repository: AnalysisRepository,
    ) -> None:
        self._sampling = sampling
        self._store = store
        self._analyzer = analyzer
        self._spatial = spatial
        self._motion = motion
        self._audio = audio
        self._repository = repository

    def execute(
        self,
        *,
        video: VideoRecord,
        analysis: AnalysisRecord,
        config: AnalysisConfig,
        request_id: str,
        cancel_check: Callable[[], None] | None = None,
    ) -> ReportStageResult:
        """Run the CPU report slice and persist stage JSON."""
        with bind_context(
            request_id=request_id,
            video_id=str(video.metadata.video_id),
            analysis_id=str(analysis.analysis_id),
            stage="report",
        ):
            try:
                result = self._execute(
                    video=video,
                    analysis=analysis,
                    config=config,
                    request_id=request_id,
                    cancel_check=cancel_check,
                )
            except AdapterError as error:
                raise wrap_adapter(error, request_id=request_id) from error
            get_logger(__name__).info(
                "report.completed",
                shot_count=result.report.summary.shot_count,
                chromatic=result.report.availability.chromatic.value,
                spatial=result.report.availability.spatial.value,
                motion=result.report.availability.motion.value,
                audio=result.report.availability.audio.value,
                tension=result.report.availability.tension.value,
            )
            return result

    def _execute(
        self,
        *,
        video: VideoRecord,
        analysis: AnalysisRecord,
        config: AnalysisConfig,
        request_id: str,
        cancel_check: Callable[[], None] | None = None,
    ) -> ReportStageResult:
        wall_started = datetime.now(tz=UTC)
        sampled = self._sampling.execute(
            video=video,
            analysis=analysis,
            config=config,
            request_id=request_id,
            cancel_check=cancel_check,
        )
        tick_cancel(cancel_check)
        started = datetime.now(tz=UTC)
        with jpeg_read_cache():
            chroma = self._measure_chromatic(
                sampled=sampled, config=config, started=started, cancel_check=cancel_check
            )
            tick_cancel(cancel_check)
            spatial, overlay_docs, observations = self._measure_spatial(
                sampled=sampled, config=config, started=started, cancel_check=cancel_check
            )
            tick_cancel(cancel_check)
            temporal, series, motion_warnings = self._measure_motion(
                sampled=sampled,
                config=config,
                observations=observations,
                started=started,
                cancel_check=cancel_check,
            )
        tick_cancel(cancel_check)
        starts = window_starts(sampled.shot_set.duration_ms(), config.tension.hop_ms)
        audio_result = self._audio.analyze(
            self._store.local_path(video.original_storage_key),
            has_audio=video.metadata.has_audio,
            duration_ms=video.metadata.duration_ms,
            config=config.audio,
            window_starts_ms=starts,
        )
        audio_ok = audio_result.status is MetricStatus.OK
        motion_ok = any(
            item.value is not None and item.value.global_motion_magnitude is not None
            for item in temporal
        )
        timeline = build_timeline(
            analysis_id=analysis.analysis_id,
            shot_set=sampled.shot_set,
            config=config,
            motion_series=series,
            audio_windows=audio_result.windows,
            audio_available=audio_ok,
            motion_available=motion_ok,
            extra_warnings=motion_warnings,
            audio_reason=audio_result.reason_code,
        )
        timeline_ref, timeline_key = self._persist_timeline(analysis.analysis_id, timeline)
        completed = datetime.now(tz=UTC)
        duration_ms = video.metadata.duration_ms
        wall_ms = max(0, int((completed - wall_started).total_seconds() * 1000))
        observe(
            "analysis_realtime_factor_milli",
            int(wall_ms * 1000 / duration_ms),
            profile="cpu_core",
        )
        report = assemble_report(
            video=video,
            analysis=analysis,
            config=config,
            shot_set=sampled.shot_set,
            chromatic=chroma,
            spatial=spatial,
            temporal=temporal,
            timeline_artifact=timeline_ref,
            motion_availability=motion_availability(temporal),
            audio_availability=audio_availability(audio_result.status),
            tension_availability=tension_availability(timeline),
            generated_at=completed,
            started_at=started,
            completed_at=completed,
        )
        prefix = f"analyses/{analysis.analysis_id.hex}"
        chroma_blob = self._store.put_replaceable(
            _chromatic_document(analysis.analysis_id, chroma, sampled.shot_set),
            storage_key=f"{prefix}/chromatics.json",
        )
        spatial_blob = self._store.put_replaceable(
            _spatial_document(analysis.analysis_id, spatial, sampled.shot_set, overlay_docs),
            storage_key=f"{prefix}/spatial.json",
        )
        report_blob = self._store.put_replaceable(
            report.model_dump_json().encode("utf-8"),
            storage_key=f"{prefix}/report.json",
        )
        self._record_blob(chroma_blob, kind="chromatics", media_type="application/json")
        self._record_blob(spatial_blob, kind="spatial", media_type="application/json")
        self._record_blob(report_blob, kind="analysis_report", media_type="application/json")
        return ReportStageResult(
            sampling=sampled,
            report=report,
            report_key=report_blob.storage_key,
            chromatics_key=chroma_blob.storage_key,
            spatial_key=spatial_blob.storage_key,
            timeline_key=timeline_key,
        )

    def _measure_chromatic(
        self,
        *,
        sampled: SamplingStageResult,
        config: AnalysisConfig,
        started: datetime,
        cancel_check: Callable[[], None] | None = None,
    ) -> tuple[ChromaticMeasurement, ...]:
        provenance = _provenance(
            method="chromatics.opencv_sklearn",
            method_version=CHROMATIC_METHOD_VERSION,
            config_hash=config.hash(),
            started_at=started,
            completed_at=datetime.now(tz=UTC),
            random_seed=config.chromatic.random_seed,
        )
        measured: list[ChromaticMeasurement] = []
        for shot in sampled.shot_set.shots:
            tick_cancel(cancel_check)
            frames = collect_shot_frames(
                sampled.manifest,
                sampled.sample_keys,
                self._store,
                shot.shot_id,
            )
            if not frames:
                computed = ChromaticComputeResult(
                    status=MetricStatus.INSUFFICIENT_DATA,
                    value=None,
                    confidence=None,
                    reason_code=_EMPTY_CHROMA,
                    evidence_sample_ids=(),
                )
            else:
                computed = self._analyzer.analyze_shot(frames, config.chromatic)
            measured.append(wrap_chromatic_measurement(computed, method=provenance))
        return tuple(measured)

    def _measure_spatial(
        self,
        *,
        sampled: SamplingStageResult,
        config: AnalysisConfig,
        started: datetime,
        cancel_check: Callable[[], None] | None = None,
    ) -> tuple[
        tuple[SpatialMeasurement, ...],
        tuple[dict[str, object], ...],
        tuple[tuple[SubjectObservation, ...], ...],
    ]:
        provenance = _provenance(
            method=f"spatial.{config.spatial.backend}",
            method_version=SPATIAL_METHOD_VERSION,
            config_hash=config.hash(),
            started_at=started,
            completed_at=datetime.now(tz=UTC),
            model_name="fake" if config.spatial.backend == "fake" else None,
        )
        measured: list[SpatialMeasurement] = []
        overlay_docs: list[dict[str, object]] = []
        observations: list[tuple[SubjectObservation, ...]] = []
        for shot in sampled.shot_set.shots:
            tick_cancel(cancel_check)
            frames = collect_spatial_frames(
                sampled.manifest,
                sampled.sample_keys,
                self._store,
                shot.shot_id,
            )
            computed = self._spatial.analyze_shot(frames, config.spatial)
            stored = self._store_overlays(computed)
            overlay_docs.append(
                {
                    "observations": [
                        json.loads(item.model_dump_json()) for item in computed.observations
                    ],
                    "overlays": stored,
                    "shot_id": str(shot.shot_id),
                }
            )
            observations.append(computed.observations)
            measured.append(wrap_spatial_measurement(computed, method=provenance))
        return tuple(measured), tuple(overlay_docs), tuple(observations)

    def _measure_motion(
        self,
        *,
        sampled: SamplingStageResult,
        config: AnalysisConfig,
        observations: tuple[tuple[SubjectObservation, ...], ...],
        started: datetime,
        cancel_check: Callable[[], None] | None = None,
    ) -> tuple[tuple[TemporalMeasurement, ...], tuple[MotionSeriesPoint, ...], tuple[str, ...]]:
        provenance = _provenance(
            method="motion.opencv_farneback",
            method_version=MOTION_METHOD_VERSION,
            config_hash=config.hash(),
            started_at=started,
            completed_at=datetime.now(tz=UTC),
        )
        measured: list[TemporalMeasurement] = []
        series: list[MotionSeriesPoint] = []
        flagged = False
        for shot, shot_observations in zip(sampled.shot_set.shots, observations, strict=True):
            tick_cancel(cancel_check)
            frames = collect_motion_frames(
                sampled.manifest,
                sampled.sample_keys,
                self._store,
                shot.shot_id,
            )
            stats: list[FlowPairStats] = []
            for pair in adjacent_motion_pairs(frames):
                boxed = attach_subject_boxes(pair, shot_observations)
                computed = self._motion.analyze_pair(boxed, config.motion)
                if computed is not None:
                    stats.append(computed)
            result = summarize_shot_motion(
                duration_ms=shot.time_range.duration_ms,
                shot_index=shot.index,
                pairs=tuple(stats),
                evidence_sample_ids=tuple(frame.sample_id for frame in frames),
                method=provenance,
            )
            measured.append(result.measurement)
            series.extend(result.series)
            flagged = flagged or result.flagged_discontinuity
        warnings = (CUT_LIKE_WARNING,) if flagged else ()
        return tuple(measured), tuple(series), warnings

    def _persist_timeline(
        self,
        analysis_id: UUID,
        timeline: Timeline,
    ) -> tuple[ArtifactRef, str]:
        payload = timeline.model_dump_json().encode("utf-8")
        digest = sha256(payload).hexdigest()
        content = self._store.put_bytes(payload, storage_key=content_storage_key(digest))
        replaceable = self._store.put_replaceable(
            payload,
            storage_key=f"analyses/{analysis_id.hex}/timeline.json",
        )
        self._record_blob(content, kind="timeline", media_type="application/json")
        self._record_blob(replaceable, kind="timeline", media_type="application/json")
        ref = ArtifactRef(
            artifact_id=uuid4(),
            kind="timeline",
            media_type="application/json",
            sha256=content.sha256,
            size_bytes=content.size_bytes,
            schema_version=SCHEMA_VERSION,
        )
        return ref, replaceable.storage_key

    def _store_overlays(self, computed: SpatialComputeResult) -> list[dict[str, str]]:
        stored: list[dict[str, str]] = []
        for sample_id, jpeg in computed.overlays:
            digest = sha256(jpeg).hexdigest()
            blob = self._store.put_bytes(jpeg, storage_key=content_storage_key(digest))
            self._record_blob(blob, kind="spatial_overlay", media_type="image/jpeg")
            stored.append(
                {
                    "sample_id": str(sample_id),
                    "storage_key": blob.storage_key,
                }
            )
        return stored

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


def assemble_report(
    *,
    video: VideoRecord,
    analysis: AnalysisRecord,
    config: AnalysisConfig,
    shot_set: ShotSet,
    chromatic: tuple[ChromaticMeasurement, ...],
    spatial: tuple[SpatialMeasurement, ...],
    generated_at: datetime,
    started_at: datetime,
    completed_at: datetime,
    temporal: tuple[TemporalMeasurement, ...] | None = None,
    timeline_artifact: ArtifactRef | None = None,
    motion_availability: StageAvailability = StageAvailability.UNAVAILABLE,
    audio_availability: StageAvailability = StageAvailability.UNAVAILABLE,
    tension_availability: StageAvailability = StageAvailability.UNAVAILABLE,
) -> AnalysisReport:
    """Build a report with chromatics, spatial, temporal, and optional timeline reference."""
    if len(chromatic) != len(shot_set.shots):
        message = "chromatic measurements must match shot count"
        raise ValueError(message)
    if len(spatial) != len(shot_set.shots):
        message = "spatial measurements must match shot count"
        raise ValueError(message)
    temporal_method = _provenance(
        method="temporal.duration_motion",
        method_version=_TEMPORAL_METHOD_VERSION,
        config_hash=config.hash(),
        started_at=started_at,
        completed_at=completed_at,
    )
    if temporal is None:
        resolved = tuple(_temporal_for(shot, temporal_method) for shot in shot_set.shots)
    else:
        if len(temporal) != len(shot_set.shots):
            message = "temporal measurements must match shot count"
            raise ValueError(message)
        resolved = temporal
    analyses = tuple(
        ShotAnalysis(
            shot=shot,
            chromatic=chroma,
            spatial=space,
            temporal=time_envelope,
        )
        for shot, chroma, space, time_envelope in zip(
            shot_set.shots, chromatic, spatial, resolved, strict=True
        )
    )
    return AnalysisReport(
        schema_version=SCHEMA_VERSION,
        analysis_id=analysis.analysis_id,
        video=video.metadata,
        generated_at=generated_at,
        pipeline_version=config.pipeline_version,
        configuration_hash=config.hash(),
        availability=ReportAvailability(
            shots=StageAvailability.COMPLETE,
            chromatic=chromatic_availability(chromatic),
            spatial=spatial_availability(spatial),
            motion=motion_availability,
            audio=audio_availability,
            tension=tension_availability,
            critic=StageAvailability.NOT_REQUESTED,
        ),
        summary=video_summary(shot_set, video.metadata.duration_ms),
        shots=analyses,
        timeline_artifact=timeline_artifact,
        critique=None,
    )


def video_summary(shot_set: ShotSet, duration_ms: int) -> VideoSummary:
    """Editing summary from validated shot intervals."""
    durations = [shot.time_range.duration_ms for shot in shot_set.shots]
    count = len(durations)
    mean = sum(durations) / count
    return VideoSummary(
        shot_count=count,
        average_shot_length_ms=mean,
        median_shot_length_ms=_median(durations),
        shots_per_minute=(60_000 * count) / duration_ms,
    )


def chromatic_availability(
    measurements: tuple[ChromaticMeasurement, ...],
) -> StageAvailability:
    """COMPLETE when every shot is OK, PARTIAL when some are, else UNAVAILABLE."""
    if not measurements:
        return StageAvailability.UNAVAILABLE
    ok = [item.status is MetricStatus.OK for item in measurements]
    if all(ok):
        return StageAvailability.COMPLETE
    if any(ok):
        return StageAvailability.PARTIAL
    return StageAvailability.UNAVAILABLE


def spatial_availability(
    measurements: tuple[SpatialMeasurement, ...],
) -> StageAvailability:
    """COMPLETE when every shot is OK or NO_SUBJECT; UNAVAILABLE when none ran."""
    if not measurements:
        return StageAvailability.UNAVAILABLE
    if all(item.status is MetricStatus.NOT_COMPUTED for item in measurements):
        return StageAvailability.UNAVAILABLE
    conclusive = {MetricStatus.OK, MetricStatus.NO_SUBJECT}
    flags = [item.status in conclusive for item in measurements]
    if all(flags):
        return StageAvailability.COMPLETE
    if any(flags):
        return StageAvailability.PARTIAL
    return StageAvailability.UNAVAILABLE


def motion_availability(
    measurements: tuple[TemporalMeasurement, ...],
) -> StageAvailability:
    """COMPLETE when every shot has global and residual magnitudes."""
    if not measurements:
        return StageAvailability.UNAVAILABLE
    present = [
        item.value is not None and item.value.global_motion_magnitude is not None
        for item in measurements
    ]
    if all(present):
        return StageAvailability.COMPLETE
    if any(present):
        return StageAvailability.PARTIAL
    return StageAvailability.UNAVAILABLE


def audio_availability(status: MetricStatus) -> StageAvailability:
    """COMPLETE only when features were computed from an audio stream."""
    if status is MetricStatus.OK:
        return StageAvailability.COMPLETE
    return StageAvailability.UNAVAILABLE


def tension_availability(timeline: Timeline) -> StageAvailability:
    """COMPLETE when the timeline has at least one point."""
    if timeline.points:
        return StageAvailability.COMPLETE
    return StageAvailability.UNAVAILABLE


def _temporal_for(shot: Shot, method: MethodProvenance) -> TemporalMeasurement:
    return TemporalMeasurement(
        status=MetricStatus.OK,
        value=TemporalValue(duration_ms=shot.time_range.duration_ms),
        method=method,
    )


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _provenance(
    *,
    method: str,
    method_version: str,
    config_hash: str,
    started_at: datetime,
    completed_at: datetime,
    random_seed: int | None = None,
    model_name: str | None = None,
) -> MethodProvenance:
    return MethodProvenance(
        method=method,
        method_version=method_version,
        config_hash=config_hash,
        code_revision=f"cine-analyzer-{__version__}",
        random_seed=random_seed,
        model_name=model_name,
        device="cpu",
        started_at=started_at,
        completed_at=completed_at,
    )


def _chromatic_document(
    analysis_id: UUID,
    measurements: tuple[ChromaticMeasurement, ...],
    shot_set: ShotSet,
) -> bytes:
    payload = {
        "analysis_id": str(analysis_id),
        "method_version": CHROMATIC_METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "shots": [
            {
                "measurement": json.loads(measurement.model_dump_json()),
                "shot_id": str(shot.shot_id),
            }
            for shot, measurement in zip(shot_set.shots, measurements, strict=True)
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _spatial_document(
    analysis_id: UUID,
    measurements: tuple[SpatialMeasurement, ...],
    shot_set: ShotSet,
    overlay_docs: tuple[dict[str, object], ...],
) -> bytes:
    payload = {
        "analysis_id": str(analysis_id),
        "method_version": SPATIAL_METHOD_VERSION,
        "schema_version": SCHEMA_VERSION,
        "shots": [
            {
                "measurement": json.loads(measurement.model_dump_json()),
                "observations": extra["observations"],
                "overlays": extra["overlays"],
                "shot_id": str(shot.shot_id),
            }
            for shot, measurement, extra in zip(
                shot_set.shots, measurements, overlay_docs, strict=True
            )
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
