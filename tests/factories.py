"""Builders for valid domain objects. Shared by unit and contract tests."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from cine_analyzer.domain.artifacts import ArtifactRef, MethodProvenance
from cine_analyzer.domain.chromatics import (
    ChromaticMeasurement,
    ChromaticValue,
    ColorSwatch,
    LabColor,
    LightingKeyLabel,
    LightnessDistribution,
    RgbColor,
)
from cine_analyzer.domain.jobs import StageCommand, StageResult
from cine_analyzer.domain.media import SamplePurpose, SampleRequest, SamplingPlan, VideoMetadata
from cine_analyzer.domain.report import (
    AnalysisReport,
    ReportAvailability,
    ShotAnalysis,
    StageAvailability,
    VideoSummary,
)
from cine_analyzer.domain.shots import Shot, ShotSet
from cine_analyzer.domain.spatial import FramingLabel, SpatialMeasurement, SpatialValue
from cine_analyzer.domain.temporal import TemporalMeasurement, TemporalValue
from cine_analyzer.domain.time import Rational, TimeRangeMs
from cine_analyzer.domain.types import SCHEMA_VERSION, MetricStatus

STAMP = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
ANALYSIS_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
VIDEO_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SHOT_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
ARTIFACT_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
SAMPLE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
DIGEST = sha256(b"cine-analyzer-fixture").hexdigest()


def make_artifact(**overrides: object) -> ArtifactRef:
    payload: dict[str, object] = {
        "artifact_id": ARTIFACT_ID,
        "kind": "probe",
        "media_type": "application/json",
        "sha256": DIGEST,
        "size_bytes": 128,
        "schema_version": SCHEMA_VERSION,
    }
    payload.update(overrides)
    return ArtifactRef.model_validate(payload)


def make_provenance(**overrides: object) -> MethodProvenance:
    payload: dict[str, object] = {
        "method": "shots.adaptive",
        "method_version": "1.0.0",
        "config_hash": DIGEST,
        "code_revision": "dev",
        "started_at": STAMP,
        "completed_at": STAMP,
    }
    payload.update(overrides)
    return MethodProvenance.model_validate(payload)


def make_video(**overrides: object) -> VideoMetadata:
    payload: dict[str, object] = {
        "video_id": VIDEO_ID,
        "original_filename": "clip.mp4",
        "content_sha256": DIGEST,
        "size_bytes": 1024,
        "duration_ms": 4000,
        "width": 1920,
        "height": 1080,
        "display_rotation_degrees": 0,
        "average_frame_rate": Rational(numerator=24, denominator=1),
        "video_codec": "h264",
        "has_audio": False,
        "probe_artifact": make_artifact(),
    }
    payload.update(overrides)
    return VideoMetadata.model_validate(payload)


def make_shot(
    *,
    index: int = 0,
    start_ms: int = 0,
    end_ms: int = 4000,
    **overrides: object,
) -> Shot:
    payload: dict[str, object] = {
        "shot_id": UUID(int=SHOT_ID.int + index),
        "index": index,
        "time_range": TimeRangeMs(start_ms=start_ms, end_ms=end_ms),
    }
    payload.update(overrides)
    return Shot.model_validate(payload)


def make_shot_set(shots: tuple[Shot, ...] | None = None, **overrides: object) -> ShotSet:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "detector": make_provenance(),
        "shots": (make_shot(),) if shots is None else shots,
    }
    payload.update(overrides)
    return ShotSet.model_validate(payload)


def make_swatch(*, rank: int, proportion: float, red: int, green: int, blue: int) -> ColorSwatch:
    return ColorSwatch(
        rank=rank,
        lab=LabColor(lstar=50.0, a=0.0, b=0.0),
        rgb=RgbColor(r=red, g=green, b=blue, hex=f"#{red:02X}{green:02X}{blue:02X}"),
        proportion=proportion,
    )


def make_chromatic_value() -> ChromaticValue:
    return ChromaticValue(
        palette=(make_swatch(rank=1, proportion=1.0, red=16, green=32, blue=48),),
        lightness=LightnessDistribution(
            mean_lstar=40.0,
            stddev_lstar=5.0,
            p10_lstar=20.0,
            p50_lstar=40.0,
            p90_lstar=60.0,
            shadow_ratio=0.2,
            highlight_ratio=0.1,
        ),
        lighting_key=LightingKeyLabel.BALANCED_ESTIMATE,
        usable_pixel_ratio=0.95,
    )


def make_spatial_value() -> SpatialValue:
    return SpatialValue(
        primary_track_id="track-1",
        subject_coverage_ratio_median=0.2,
        subject_height_ratio_median=0.4,
        thirds_proximity_score=0.5,
        thirds_proximity_p10=0.3,
        center_proximity_score=0.4,
        framing=FramingLabel.MEDIUM_ESTIMATE,
        framing_confidence=0.6,
        track_coverage_ratio=0.9,
    )


def make_temporal_value(*, duration_ms: int = 4000) -> TemporalValue:
    return TemporalValue(duration_ms=duration_ms)


def make_ok_chromatic() -> ChromaticMeasurement:
    return ChromaticMeasurement(
        status=MetricStatus.OK,
        value=make_chromatic_value(),
        method=make_provenance(),
    )


def make_unavailable_spatial(*, reason_code: str = "detector_not_installed") -> SpatialMeasurement:
    return SpatialMeasurement(
        status=MetricStatus.NOT_COMPUTED,
        value=None,
        reason_code=reason_code,
        method=make_provenance(),
    )


def make_ok_temporal(*, duration_ms: int = 4000) -> TemporalMeasurement:
    return TemporalMeasurement(
        status=MetricStatus.OK,
        value=make_temporal_value(duration_ms=duration_ms),
        method=make_provenance(),
    )


def make_shot_analysis(shot: Shot | None = None) -> ShotAnalysis:
    chosen = shot or make_shot()
    return ShotAnalysis(
        shot=chosen,
        chromatic=make_ok_chromatic(),
        spatial=make_unavailable_spatial(),
        temporal=make_ok_temporal(duration_ms=chosen.time_range.duration_ms),
    )


def make_availability(**overrides: object) -> ReportAvailability:
    payload: dict[str, object] = {
        "shots": StageAvailability.COMPLETE,
        "chromatic": StageAvailability.COMPLETE,
        "spatial": StageAvailability.UNAVAILABLE,
        "motion": StageAvailability.UNAVAILABLE,
        "audio": StageAvailability.UNAVAILABLE,
        "tension": StageAvailability.UNAVAILABLE,
        "critic": StageAvailability.NOT_REQUESTED,
    }
    payload.update(overrides)
    return ReportAvailability.model_validate(payload)


def make_report(**overrides: object) -> AnalysisReport:
    shot = make_shot()
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "video": make_video(),
        "generated_at": STAMP,
        "pipeline_version": "0.1.0",
        "configuration_hash": DIGEST,
        "availability": make_availability(),
        "summary": VideoSummary(
            shot_count=1,
            average_shot_length_ms=4000.0,
            median_shot_length_ms=4000.0,
            shots_per_minute=15.0,
        ),
        "shots": (make_shot_analysis(shot),),
    }
    payload.update(overrides)
    return AnalysisReport.model_validate(payload)


def make_sampling_plan(requests: tuple[SampleRequest, ...] | None = None) -> SamplingPlan:
    default = (
        SampleRequest(
            sample_id=SAMPLE_ID,
            shot_id=SHOT_ID,
            requested_ms=2000,
            purposes=(SamplePurpose.CHROMATIC, SamplePurpose.EVIDENCE),
        ),
    )
    return SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="1.0.0",
        requests=requests if requests is not None else default,
    )


def make_stage_command(**overrides: object) -> StageCommand:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "stage_name": "shots",
        "input_artifact_ids": (ARTIFACT_ID,),
        "configuration_hash": DIGEST,
        "pipeline_version": "0.1.0",
        "requested_at": STAMP,
        "trace_id": "trace-1",
    }
    payload.update(overrides)
    return StageCommand.model_validate(payload)


def make_stage_result(**overrides: object) -> StageResult:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "stage_name": "shots",
        "attempt": 1,
        "output_artifact_ids": (ARTIFACT_ID,),
        "provenance": make_provenance(),
    }
    payload.update(overrides)
    return StageResult.model_validate(payload)
