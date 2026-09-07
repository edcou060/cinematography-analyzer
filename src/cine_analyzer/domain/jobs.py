"""Job and stage state machines, plus the small envelopes that cross a process boundary.

Terminal states never move backward. A retry is a new stage-run attempt, not a
regression of a finished one. Queue payloads carry identifiers, never frames.
"""

from enum import StrEnum
from typing import Annotated, Final, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from cine_analyzer.domain.artifacts import MethodProvenance
from cine_analyzer.domain.errors import SafeError
from cine_analyzer.domain.types import SCHEMA_VERSION, Score, Sha256Hex, StrictModel

__all__ = [
    "ANALYSIS_TRANSITIONS",
    "QUEUE_PAYLOAD_MAX_BYTES",
    "STAGE_TRANSITIONS",
    "AnalysisState",
    "AnalysisStatusResponse",
    "IllegalStateTransitionError",
    "StageCommand",
    "StageResult",
    "StageState",
    "analysis_is_terminal",
    "is_partial_outcome",
    "stage_is_terminal",
    "transition_analysis",
    "transition_stage",
]

QUEUE_PAYLOAD_MAX_BYTES: Final = 8192


class AnalysisState(StrEnum):
    """Overall analysis state. Progress is derived from stages, not from log text."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class StageState(StrEnum):
    """One attempt of one stage. A retry allocates a new attempt in PENDING."""

    PENDING = "PENDING"
    LEASED = "LEASED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    SKIPPED = "SKIPPED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELED = "CANCELED"


ANALYSIS_TRANSITIONS: Final[dict[AnalysisState, frozenset[AnalysisState]]] = {
    AnalysisState.QUEUED: frozenset({AnalysisState.RUNNING, AnalysisState.CANCELED}),
    AnalysisState.RUNNING: frozenset(
        {
            AnalysisState.SUCCEEDED,
            AnalysisState.PARTIAL,
            AnalysisState.FAILED,
            AnalysisState.CANCEL_REQUESTED,
        }
    ),
    AnalysisState.CANCEL_REQUESTED: frozenset({AnalysisState.CANCELED, AnalysisState.FAILED}),
    AnalysisState.CANCELED: frozenset(),
    AnalysisState.SUCCEEDED: frozenset(),
    AnalysisState.PARTIAL: frozenset(),
    AnalysisState.FAILED: frozenset(),
}

STAGE_TRANSITIONS: Final[dict[StageState, frozenset[StageState]]] = {
    StageState.PENDING: frozenset({StageState.LEASED, StageState.SKIPPED, StageState.CANCELED}),
    StageState.LEASED: frozenset({StageState.RUNNING, StageState.CANCELED, StageState.PENDING}),
    StageState.RUNNING: frozenset(
        {
            StageState.SUCCEEDED,
            StageState.FAILED_RETRYABLE,
            StageState.FAILED_TERMINAL,
            StageState.CANCELED,
        }
    ),
    StageState.SUCCEEDED: frozenset(),
    StageState.SKIPPED: frozenset(),
    StageState.FAILED_RETRYABLE: frozenset(),
    StageState.FAILED_TERMINAL: frozenset(),
    StageState.CANCELED: frozenset(),
}


class IllegalStateTransitionError(ValueError):
    """Raised when a caller asks a state machine to move to an illegal target."""

    def __init__(self, entity: str, current: StrEnum, target: StrEnum) -> None:
        self.entity = entity
        self.current = current
        self.target = target
        super().__init__(f"illegal {entity} transition: {current} -> {target}")


def analysis_is_terminal(state: AnalysisState) -> bool:
    """True when the analysis can no longer change state."""
    return not ANALYSIS_TRANSITIONS[state]


def stage_is_terminal(state: StageState) -> bool:
    """True when this attempt can no longer change state.

    ``FAILED_RETRYABLE`` is terminal for the attempt. The next try is a new attempt.
    """
    return not STAGE_TRANSITIONS[state]


def is_partial_outcome(
    *,
    required_dependencies_terminal: bool,
    optional_stage_failed: bool,
) -> bool:
    """``PARTIAL``: every required dependency finished and at least one optional stage failed."""
    return required_dependencies_terminal and optional_stage_failed


def transition_analysis(current: AnalysisState, target: AnalysisState) -> AnalysisState:
    """Return ``target`` if the analysis may move there, otherwise raise."""
    if target not in ANALYSIS_TRANSITIONS[current]:
        entity = "analysis"
        raise IllegalStateTransitionError(entity, current, target)
    return target


def transition_stage(current: StageState, target: StageState) -> StageState:
    """Return ``target`` if this stage attempt may move there, otherwise raise."""
    if target not in STAGE_TRANSITIONS[current]:
        entity = "stage"
        raise IllegalStateTransitionError(entity, current, target)
    return target


class StageCommand(StrictModel):
    """Work request passed across a process boundary. Identifiers only."""

    schema_version: Annotated[str, Field(description="Stage-command schema version.")]
    analysis_id: UUID
    stage_name: Annotated[str, Field(min_length=1, max_length=64)]
    input_artifact_ids: tuple[UUID, ...]
    configuration_hash: Sha256Hex
    pipeline_version: Annotated[str, Field(min_length=1, max_length=64)]
    requested_at: AwareDatetime
    trace_id: Annotated[str, Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def schema_is_supported(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported stage-command schema_version {self.schema_version!r}"
            raise ValueError(message)
        return self


class StageResult(StrictModel):
    """Outcome of one stage attempt. Output is named by artifact IDs."""

    schema_version: Annotated[str, Field(description="Stage-result schema version.")]
    analysis_id: UUID
    stage_name: Annotated[str, Field(min_length=1, max_length=64)]
    attempt: Annotated[int, Field(ge=1)]
    output_artifact_ids: tuple[UUID, ...]
    provenance: MethodProvenance
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def schema_is_supported(self) -> Self:
        if self.schema_version != SCHEMA_VERSION:
            message = f"unsupported stage-result schema_version {self.schema_version!r}"
            raise ValueError(message)
        return self


class AnalysisStatusResponse(StrictModel):
    """Client status view. Reads from authoritative state, not from a broker."""

    analysis_id: UUID
    state: AnalysisState
    progress: Score
    completed_stages: tuple[str, ...]
    active_stages: tuple[str, ...]
    unavailable_stages: tuple[str, ...]
    error: SafeError | None = None
