# Data contracts and schema strategy

## 1. Contract principles

The data model is the spine of the system. Every API, worker, database row, artifact, dashboard panel, and critic prompt must agree on these rules:

1. **Reject structural drift.** Boundary models use `ConfigDict(extra="forbid")`.
2. **Version every durable envelope.** Store `schema_version`, not merely an application version.
3. **Persist integer time.** Milliseconds avoid floating-point equality and JSON ambiguity.
4. **Represent absence.** A missing value always has a machine-readable status/reason.
5. **Preserve evidence.** A metric points to the samples/time ranges used to derive it.
6. **Preserve provenance.** Method, config, code, model, weights, runtime, and seed are queryable.
7. **Separate facts from estimates.** A duration is measured; a framing label is a heuristic estimate.
8. **Keep queue messages small.** Cross-process commands reference artifacts and rows.
9. **Prefer immutable outputs.** New methods create new result versions instead of mutating history.

## 2. Naming and units

| Concept | Canonical representation |
| --- | --- |
| Identifier | UUID string at external boundaries |
| Time position/duration | integer milliseconds, suffix `_ms` |
| Frame rate | numerator and denominator; float only for display |
| Ratio/score | float in `[0, 1]`, explicit suffix where useful |
| Percentage | avoid internally; format ratios as percentages in UI |
| Lightness | CIE L-star in `[0, 100]`, suffix `_lstar` |
| OpenCV 8-bit Lab L channel | never expose as L-star without conversion |
| Color proportion | float in `[0, 1]`; palette sorted descending |
| File size | integer bytes, suffix `_bytes` |
| Audio sample rate | integer hertz, suffix `_hz` |
| Confidence | calibrated/heuristic ratio plus method, never implied |

## 3. Core Pydantic v2 model

The following is a target contract, not a demand to paste all code during Phase 02. Implement it in coherent modules and add JSON-schema snapshot tests.

```python
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Score = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-F]{6}$")]
T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class MetricStatus(StrEnum):
    OK = "OK"
    NOT_COMPUTED = "NOT_COMPUTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_SUBJECT = "NO_SUBJECT"
    NO_AUDIO = "NO_AUDIO"
    FAILED = "FAILED"


class TimeRangeMs(StrictModel):
    start_ms: Annotated[int, Field(ge=0)]
    end_ms: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def end_follows_start(self) -> "TimeRangeMs":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class ArtifactRef(StrictModel):
    artifact_id: UUID
    kind: str
    media_type: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(ge=0)]
    schema_version: str | None = None


class EvidenceFrame(StrictModel):
    sample_id: UUID
    requested_ms: Annotated[int, Field(ge=0)]
    decoded_ms: Annotated[int, Field(ge=0)]
    frame_index: Annotated[int, Field(ge=0)] | None = None
    image: ArtifactRef
    purposes: tuple[str, ...]


class MethodProvenance(StrictModel):
    method: str
    method_version: str
    config_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    code_revision: str
    random_seed: int | None = None
    model_name: str | None = None
    model_package_version: str | None = None
    weights_sha256: str | None = None
    device: str | None = None
    started_at: datetime
    completed_at: datetime


class Measurement(StrictModel, Generic[T]):
    status: MetricStatus
    value: T | None
    confidence: Score | None = None
    reason_code: str | None = None
    evidence_sample_ids: tuple[UUID, ...] = ()
    method: MethodProvenance

    @model_validator(mode="after")
    def status_matches_value(self) -> "Measurement[T]":
        if self.status == MetricStatus.OK and self.value is None:
            raise ValueError("OK measurement requires a value")
        if self.status != MetricStatus.OK and self.value is not None:
            raise ValueError("non-OK measurement must not contain a value")
        return self
```

### Why an explicit `Measurement` envelope matters

`null` alone is ambiguous: no audio, no person, not requested, failed, or an old schema could all look identical. The envelope lets the aggregator and dashboard degrade truthfully while preserving method-level provenance.

## 4. Media and sampling contracts

```python
class Rational(StrictModel):
    numerator: int
    denominator: Annotated[int, Field(gt=0)]


class VideoMetadata(StrictModel):
    video_id: UUID
    original_filename: str
    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(gt=0)]
    duration_ms: Annotated[int, Field(gt=0)]
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    display_rotation_degrees: Literal[0, 90, 180, 270]
    average_frame_rate: Rational
    real_frame_rate: Rational | None
    video_codec: str
    pixel_format: str | None
    has_audio: bool
    audio_codec: str | None
    probe_artifact: ArtifactRef


class SamplePurpose(StrEnum):
    CHROMATIC = "CHROMATIC"
    COMPOSITION = "COMPOSITION"
    MOTION = "MOTION"
    EVIDENCE = "EVIDENCE"


class SampleRequest(StrictModel):
    sample_id: UUID
    shot_id: UUID
    requested_ms: Annotated[int, Field(ge=0)]
    purposes: tuple[SamplePurpose, ...]


class SamplingPlan(StrictModel):
    schema_version: Literal["1.0"]
    analysis_id: UUID
    video_id: UUID
    method_version: str
    requests: tuple[SampleRequest, ...]


class SampleStatus(StrEnum):
    DECODED = "DECODED"
    UNAVAILABLE = "UNAVAILABLE"


class SampleResult(StrictModel):
    sample_id: UUID
    shot_id: UUID
    requested_ms: Annotated[int, Field(ge=0)]
    decoded_ms: Annotated[int, Field(ge=0)] | None = None
    frame_index: Annotated[int, Field(ge=0)] | None = None
    purposes: tuple[SamplePurpose, ...]
    status: SampleStatus
    image: ArtifactRef | None = None
    unavailable_reason: str | None = None


class SamplingManifest(StrictModel):
    schema_version: Literal["1.0"]
    analysis_id: UUID
    video_id: UUID
    method_version: str
    plan: SamplingPlan
    results: tuple[SampleResult, ...]
```

`requested_ms` and `decoded_ms` are both stored. A frame whose decoded timestamp falls outside the requested shot is `UNAVAILABLE`; the extractor never substitutes a neighbouring shot.

Hashed shot-detector fields (`working_width`, `threshold`, `min_content_val`, `debug`) live on `ShotsConfig` so a threshold change cannot reuse a previous analysis identity (ADR-0010).

For variable-frame-rate media, `requested_ms` and `decoded_ms` are authoritative. Avoid deriving timestamps as `frame_index / fps` except for constant-frame-rate fixtures where that assumption is explicit.

## 5. Shot contracts

```python
class TransitionKind(StrEnum):
    CUT = "CUT"
    FADE = "FADE"
    UNKNOWN = "UNKNOWN"


class ShotBoundary(StrictModel):
    boundary_id: UUID
    position_ms: Annotated[int, Field(gt=0)]
    transition: TransitionKind
    detector_score: float | None = None
    evidence_before: UUID | None = None
    evidence_after: UUID | None = None


class Shot(StrictModel):
    shot_id: UUID
    index: Annotated[int, Field(ge=0)]
    time_range: TimeRangeMs
    incoming_boundary_id: UUID | None
    outgoing_boundary_id: UUID | None
    representative_sample_id: UUID | None


class ShotSet(StrictModel):
    schema_version: Literal["1.0"]
    analysis_id: UUID
    detector: MethodProvenance
    shots: tuple[Shot, ...]

    @model_validator(mode="after")
    def shots_are_ordered_and_nonoverlapping(self) -> "ShotSet":
        for expected_index, shot in enumerate(self.shots):
            if shot.index != expected_index:
                raise ValueError("shot indices must be contiguous from zero")
        for left, right in zip(self.shots, self.shots[1:], strict=False):
            if left.time_range.end_ms != right.time_range.start_ms:
                raise ValueError("shot time ranges must be contiguous")
        return self
```

The detector may output “scenes” in its own API. Translate that third-party term at the adapter boundary. Clip start and end are outer bounds, not `ShotBoundary` rows. A clip with no internal edit is one shot covering `[0, duration_ms)`.

## 6. Chromatic contracts

```python
class LabColor(StrictModel):
    lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    a: Annotated[float, Field(ge=-128.0, le=127.0)]
    b: Annotated[float, Field(ge=-128.0, le=127.0)]


class RgbColor(StrictModel):
    r: Annotated[int, Field(ge=0, le=255)]
    g: Annotated[int, Field(ge=0, le=255)]
    b: Annotated[int, Field(ge=0, le=255)]
    hex: HexColor


class ColorSwatch(StrictModel):
    rank: Annotated[int, Field(ge=1, le=5)]
    lab: LabColor
    rgb: RgbColor
    proportion: Score


class LightingKeyLabel(StrEnum):
    LOW_KEY_ESTIMATE = "LOW_KEY_ESTIMATE"
    HIGH_KEY_ESTIMATE = "HIGH_KEY_ESTIMATE"
    BALANCED_ESTIMATE = "BALANCED_ESTIMATE"


class LightnessDistribution(StrictModel):
    mean_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    stddev_lstar: NonNegativeFloat
    p10_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    p50_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    p90_lstar: Annotated[float, Field(ge=0.0, le=100.0)]
    shadow_ratio: Score
    highlight_ratio: Score


class ChromaticValue(StrictModel):
    palette: Annotated[tuple[ColorSwatch, ...], Field(min_length=1, max_length=5)]
    lightness: LightnessDistribution
    lighting_key: LightingKeyLabel
    usable_pixel_ratio: Score


ChromaticMeasurement = Measurement[ChromaticValue]
```

Palette swatches are always sorted by decreasing proportion, then stable color ordering for ties. Proportions sum to approximately one; tests define the tolerance.

Hashed chromatic fields (`working_max_side`, MiniBatchKMeans `kmeans_batch_size`/`kmeans_n_init`, `delta_e_merge`, letterbox cutoffs, shadow/highlight L* cutoffs, `min_swatch_proportion`, and nested `lighting_key_rules`) live on `ChromaticConfig` so a threshold change cannot reuse a previous analysis identity (ADR-0011). Lighting-key values are estimates; the continuous L* distribution is stored beside every label.

## 7. Spatial contracts

```python
class BoxNorm(StrictModel):
    x_min: Score
    y_min: Score
    x_max: Score
    y_max: Score

    @model_validator(mode="after")
    def valid_box(self) -> "BoxNorm":
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("invalid normalized box")
        return self


class SubjectObservation(StrictModel):
    track_id: str
    sample_id: UUID
    class_name: str
    detector_confidence: Score
    box: BoxNorm
    centroid_x: Score
    centroid_y: Score
    mask_artifact: ArtifactRef | None = None


class FramingLabel(StrEnum):
    EXTREME_WIDE_ESTIMATE = "EXTREME_WIDE_ESTIMATE"
    WIDE_ESTIMATE = "WIDE_ESTIMATE"
    MEDIUM_ESTIMATE = "MEDIUM_ESTIMATE"
    CLOSE_UP_ESTIMATE = "CLOSE_UP_ESTIMATE"
    EXTREME_CLOSE_UP_ESTIMATE = "EXTREME_CLOSE_UP_ESTIMATE"
    UNDETERMINED = "UNDETERMINED"


class SpatialValue(StrictModel):
    primary_track_id: str
    subject_coverage_ratio_median: Score
    subject_height_ratio_median: Score
    thirds_proximity_score: Score
    thirds_proximity_p10: Score
    center_proximity_score: Score
    framing: FramingLabel
    framing_confidence: Score
    track_coverage_ratio: Score


SpatialMeasurement = Measurement[SpatialValue]
```

Raw observations may live in a stage artifact rather than the report response. The report keeps summaries and evidence references. “Primary subject” is a documented selection rule, not identity recognition.

Hashed spatial fields (`thirds_sigma`, `track_iou_min`, nested `primary_track_weights`, and nested `framing_rules` / `framing_rules_v1`) live on `SpatialConfig` so a threshold change cannot reuse a previous analysis identity (ADR-0013). Base backends are `none` and `fake` (ADR-0014). Thirds proximity is geometric proximity, not composition quality. Framing labels are estimates; `NO_SUBJECT` carries no zero-valued `SpatialValue`. Default installs report reason `detector_not_installed`.

## 8. Temporal, audio, and tension contracts

```python
class TemporalValue(StrictModel):
    duration_ms: Annotated[int, Field(gt=0)]
    motion_magnitude_median: NonNegativeFloat | None
    global_motion_magnitude: NonNegativeFloat | None
    residual_motion_magnitude: NonNegativeFloat | None
    motion_magnitude_p90: NonNegativeFloat | None = None
    flow_valid_ratio: Score | None = None
    direction_consistency: Score | None = None


class AudioWindowValue(StrictModel):
    rms_dbfs: float
    onset_strength: NonNegativeFloat
    spectral_flux: NonNegativeFloat
    loudness_lufs_short_term: float | None


class TensionComponents(StrictModel):
    cut_activity: Score
    audio_activity: Score
    motion_activity: Score
    combined_proxy: Score


class TimelinePoint(StrictModel):
    at_ms: Annotated[int, Field(ge=0)]
    shot_index: Annotated[int, Field(ge=0)]
    tension: TensionComponents
    audio: AudioWindowValue | None


class Timeline(StrictModel):
    schema_version: str
    analysis_id: UUID
    hop_ms: int = 500
    window_ms: int = 1000
    method_version: str = "tension-v1"
    weights: TensionWeights
    effective_weights: TensionWeights
    warnings: tuple[str, ...] = ()
    points: tuple[TimelinePoint, ...]


TemporalMeasurement = Measurement[TemporalValue]
```

The timeline stores each component. Never persist only the combined curve; users must be able to see why it rose. Camera-movement labels are not part of this contract. `loudness_lufs_short_term` is optional and remains unset until a loudness library is chosen (ADR-0016).

Hashed motion fields (`working_max_side`, `discontinuity_diag_per_s`, nested `farneback`) live on `MotionConfig` (ADR-0015). Hashed audio `window_ms` lives on `AudioConfig` (ADR-0016). Hashed tension fields (`hop_ms`, `cut_sigma_ms`, `cut_reference`, robust-normalization percentiles, `epsilon`) live on `TensionConfig` (ADR-0017). Timeline hop is the shared integer-millisecond grid.

## 9. Report contract

```python
class StageAvailability(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_REQUESTED = "NOT_REQUESTED"


class ShotAnalysis(StrictModel):
    shot: Shot
    chromatic: ChromaticMeasurement
    spatial: SpatialMeasurement
    temporal: TemporalMeasurement


class VideoSummary(StrictModel):
    shot_count: Annotated[int, Field(ge=1)]
    average_shot_length_ms: Annotated[float, Field(gt=0)]
    median_shot_length_ms: Annotated[float, Field(gt=0)]
    shots_per_minute: NonNegativeFloat


class Critique(StrictModel):
    status: MetricStatus
    text: Annotated[str, Field(max_length=1200)] | None
    model_name: str | None
    prompt_version: str | None
    input_report_sha256: str | None


class AnalysisReport(StrictModel):
    schema_version: Literal["1.0"]
    analysis_id: UUID
    video: VideoMetadata
    generated_at: datetime
    pipeline_version: str
    configuration_hash: str
    availability: dict[str, StageAvailability]
    summary: VideoSummary
    shots: tuple[ShotAnalysis, ...]
    timeline_artifact: ArtifactRef | None
    critique: Critique | None = None
```

In implementation, prefer a typed availability model over an unrestricted dictionary once the stage set stabilizes. The example keeps the idea concise.

## 10. Task and stage envelopes

Queue payloads are intentionally boring:

```python
class StageCommand(StrictModel):
    schema_version: Literal["1.0"]
    analysis_id: UUID
    stage_name: str
    input_artifact_ids: tuple[UUID, ...]
    configuration_hash: str
    pipeline_version: str
    requested_at: datetime
    trace_id: str


class StageResult(StrictModel):
    schema_version: Literal["1.0"]
    analysis_id: UUID
    stage_name: str
    attempt: Annotated[int, Field(ge=1)]
    output_artifact_ids: tuple[UUID, ...]
    provenance: MethodProvenance
    warnings: tuple[str, ...] = ()
```

The command does not include a local path because local paths have no meaning on another host. The repository resolves artifact IDs into authorized locations.

## 11. Job and error contracts

```python
class AnalysisState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class SafeError(StrictModel):
    code: str
    message: str
    retryable: bool
    stage: str | None = None
    request_id: str
    details: tuple[dict[str, str], ...] = ()


class AnalysisStatusResponse(StrictModel):
    analysis_id: UUID
    state: AnalysisState
    progress: Score
    completed_stages: tuple[str, ...]
    active_stages: tuple[str, ...]
    unavailable_stages: tuple[str, ...]
    error: SafeError | None = None
```

Internal exceptions retain stack traces, subprocess stderr, paths, and worker data in protected logs. `SafeError` is the only error shape exposed to clients.

### Error taxonomy

| Prefix | Class | Retry behavior |
| --- | --- | --- |
| `MEDIA_` | corrupt, unsupported, limit violation | terminal |
| `PROBE_` | timeout, parser, subprocess | retry only transient resource failure |
| `SHOT_` | detector or boundary validation | bounded retry |
| `ARTIFACT_` | missing, checksum, storage I/O | retry transient I/O; checksum terminal |
| `MODEL_` | unavailable weights, invalid output | usually terminal until deployment fixed |
| `RESOURCE_` | OOM, disk full, timeout | one controlled degradation or retry |
| `SCHEMA_` | contract violation | terminal and alert-worthy |
| `CANCELED_` | cooperative cancel | terminal canceled |

## 12. Canonical configuration hashing

The same semantic configuration must hash identically regardless of dictionary ordering or formatting.

1. Validate with the Pydantic config model.
2. Serialize with `model_dump(mode="json", exclude_none=False)`.
3. Use sorted keys, UTF-8, compact separators, and finite JSON numbers.
4. Hash the bytes with SHA-256.
5. Include the pipeline version separately in the analysis key.

```python
import hashlib
import json


def canonical_hash(model: StrictModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json", exclude_none=False),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

Snapshot-test representative configs. A change to serialization that invalidates cache identity requires an ADR.

## 13. Database constraints

Pydantic validation is not sufficient. Add database constraints for invariant data:

- unique `videos.content_sha256` where deduplication is desired;
- unique analysis key across video/config/pipeline version;
- check `end_ms > start_ms`;
- check ratios between zero and one;
- unique `(analysis_id, shot_index)`;
- unique successful stage output for `(analysis_id, stage_name, method_version)`;
- foreign keys from reports and stage runs to artifact metadata;
- terminal-state update guards in repository logic;
- indexes on analysis state, created time, content hash, and artifact retention deadline.

Use Alembic migrations. Never call `metadata.create_all()` as the production migration strategy.

Phase 08 tables (ADR-0018): `videos`, `analyses`, `stage_runs`, `shots`,
`artifacts`, `report_summaries`, `critique_runs`. Stage completion is a
compare-and-set on `lease_token`. A partial unique index allows one
`SUCCEEDED` row per `(analysis_id, stage_name)`. The CLI SQLite file is not
this schema.

## 14. Schema compatibility policy

### Additive change

A new optional field with a defined default may remain in schema `1.x` if old readers can ignore it only at explicitly version-tolerant storage boundaries. Public strict models still select the correct version adapter.

### Breaking change

Renaming fields, changing units, narrowing meanings, changing enum values, or changing formula semantics requires:

1. new schema or method major version;
2. migration or side-by-side reader;
3. JSON-schema fixture for both versions;
4. API negotiation/deprecation note;
5. report regeneration policy.

### Method change without shape change

If a threshold or algorithm changes but the JSON shape does not, increment `method_version` and `pipeline_version`. Do not reuse cached outputs from the old method.

## 15. Contract test suite

Phase 02 is complete only when tests prove:

- unknown fields are rejected;
- invalid time ranges and boxes are rejected;
- non-OK measurements cannot contain values;
- OK measurements require values;
- score bounds are enforced;
- shot intervals are ordered and contiguous;
- palette ordering/proportion tolerance is enforced;
- model JSON schema is snapshotted;
- serialize -> deserialize round trips preserve equality;
- canonical config hashes ignore key order but change when semantics change;
- previous supported schema fixtures still parse through their version adapter.
