"""Control-plane ports: leases, job state, and report metadata.

Domain models do not import SQLAlchemy. The PostgreSQL adapter implements this.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState, StageState
from cine_analyzer.domain.report import Critique, ReportAvailability, VideoSummary
from cine_analyzer.ports.ingestion import AnalysisRecord, AnalysisRepository, VideoRecord

__all__ = [
    "PIPELINE_STAGES",
    "STAGE_PROGRESS_WEIGHTS",
    "AnalysisJob",
    "ArtifactRecord",
    "CritiqueRunRecord",
    "JobRepository",
    "ReportSummaryRecord",
    "ShotIntervalRecord",
    "StageLease",
    "StageRunRecord",
]

PIPELINE_STAGES: tuple[str, ...] = ("sampling", "report", "aggregate")
STAGE_PROGRESS_WEIGHTS: dict[str, float] = {
    "sampling": 0.40,
    "report": 0.50,
    "aggregate": 0.10,
}


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    """Analysis identity plus control-plane fields the status endpoint needs."""

    record: AnalysisRecord
    progress: float
    config: AnalysisConfig
    failure_code: str | None
    failure_message: str | None
    report_artifact_id: UUID | None
    timeline_artifact_id: UUID | None


@dataclass(frozen=True, slots=True)
class StageRunRecord:
    """One attempt of one leased stage."""

    stage_run_id: UUID
    analysis_id: UUID
    stage_name: str
    attempt: int
    state: StageState
    lease_token: UUID | None
    worker_id: str | None
    lease_expires_at: datetime | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class StageLease:
    """Token that must match for heartbeat, start, complete, or fail."""

    stage_run_id: UUID
    analysis_id: UUID
    stage_name: str
    attempt: int
    token: UUID
    worker_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Artifact metadata used to authorize a stream."""

    artifact_id: UUID
    kind: str
    media_type: str
    sha256: str
    size_bytes: int
    storage_key: str
    analysis_id: UUID | None


@dataclass(frozen=True, slots=True)
class ShotIntervalRecord:
    """Persisted shot interval for the shot-detail index."""

    shot_id: UUID
    analysis_id: UUID
    shot_index: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class ReportSummaryRecord:
    """Small report header stored beside the canonical JSON artifact."""

    analysis_id: UUID
    summary: VideoSummary
    availability: ReportAvailability
    report_artifact_id: UUID
    timeline_artifact_id: UUID | None


@dataclass(frozen=True, slots=True)
class CritiqueRunRecord:
    """One stored interpretation. Regenerable; cannot write measurement columns."""

    critique_run_id: UUID
    analysis_id: UUID
    critique: Critique
    created_at: datetime


class JobRepository(AnalysisRepository, Protocol):
    """PostgreSQL control-plane store. Compare-and-set is mandatory on leases."""

    def ping(self) -> None:
        """Fail if the database is not reachable."""

    def count_inflight(self) -> int:
        """Count analyses in QUEUED, RUNNING, or CANCEL_REQUESTED."""

    def close(self) -> None:
        """Release the engine pool."""

    def get_video(self, video_id: UUID) -> VideoRecord | None:
        """Primary-key video lookup."""

    def get_analysis(self, analysis_id: UUID) -> AnalysisRecord | None:
        """Primary-key analysis lookup."""

    def load_job(self, analysis_id: UUID) -> AnalysisJob | None:
        """Analysis row including config snapshot and progress."""

    def record_config(self, analysis_id: UUID, config: AnalysisConfig) -> None:
        """Persist the hashed config body so a worker can reconstruct it."""

    def ensure_pending_stages(
        self, analysis_id: UUID, stage_names: tuple[str, ...] = PIPELINE_STAGES
    ) -> None:
        """Idempotently insert attempt-1 PENDING rows."""

    def list_stage_runs(self, analysis_id: UUID) -> tuple[StageRunRecord, ...]:
        """All attempts for one analysis, ordered by stage then attempt."""

    def claim_queued(self, *, worker_id: str, now: datetime) -> AnalysisRecord | None:
        """QUEUED → RUNNING for one row, or None if the queue is empty."""

    def request_cancel(self, analysis_id: UUID, *, now: datetime) -> AnalysisRecord | None:
        """Record cooperative cancellation. None if the analysis does not exist."""

    def set_analysis_state(
        self,
        analysis_id: UUID,
        *,
        expected: AnalysisState,
        target: AnalysisState,
        progress: float | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
        report_artifact_id: UUID | None = None,
        timeline_artifact_id: UUID | None = None,
    ) -> bool:
        """Compare-and-set overall analysis state. False if expected does not match."""

    def acquire_stage(
        self,
        analysis_id: UUID,
        stage_name: str,
        *,
        worker_id: str,
        ttl_ms: int,
        now: datetime,
    ) -> StageLease | None:
        """Claim PENDING or an expired lease. None if another worker holds it."""

    def start_stage(self, lease: StageLease, *, now: datetime) -> bool:
        """LEASED → RUNNING using the lease token."""

    def heartbeat_stage(self, lease: StageLease, *, ttl_ms: int, now: datetime) -> bool:
        """Extend expiry. False if the token no longer matches."""

    def complete_stage(self, lease: StageLease, *, now: datetime) -> bool:
        """RUNNING → SUCCEEDED using the lease token."""

    def fail_stage(
        self,
        lease: StageLease,
        *,
        terminal: bool,
        code: str,
        message: str,
        now: datetime,
    ) -> bool:
        """RUNNING → FAILED_TERMINAL or FAILED_RETRYABLE using the lease token."""

    def cancel_stage(self, analysis_id: UUID, stage_name: str, attempt: int) -> bool:
        """PENDING/LEASED/RUNNING → CANCELED for an attempt."""

    def insert_retry_attempt(self, analysis_id: UUID, stage_name: str) -> StageRunRecord:
        """Allocate the next PENDING attempt after FAILED_RETRYABLE."""

    def get_artifact(self, artifact_id: UUID) -> ArtifactRecord | None:
        """Authorize an artifact stream by id."""

    def get_artifact_by_storage_key(self, storage_key: str) -> ArtifactRecord | None:
        """Look up artifact metadata by canonical storage key."""

    def save_shots(self, analysis_id: UUID, shots: tuple[ShotIntervalRecord, ...]) -> None:
        """Replace shot intervals for one analysis."""

    def get_shot(self, analysis_id: UUID, shot_id: UUID) -> ShotIntervalRecord | None:
        """One shot interval, or None."""

    def save_report_summary(self, record: ReportSummaryRecord) -> None:
        """Upsert the small report header."""

    def get_report_summary(self, analysis_id: UUID) -> ReportSummaryRecord | None:
        """Saved summary, or None if aggregation has not run."""

    def save_critique(self, record: CritiqueRunRecord) -> None:
        """Insert a critique row. Lookup-before-insert is the caller's concern."""

    def get_latest_critique(self, analysis_id: UUID) -> CritiqueRunRecord | None:
        """Newest critique for an analysis, or None."""

    def get_critique_by_identity(
        self,
        analysis_id: UUID,
        *,
        prompt_version: str,
        model_name: str,
        input_report_sha256: str,
    ) -> CritiqueRunRecord | None:
        """Idempotent lookup for the same prompt, model, and report digest."""

    def link_artifact(self, artifact_id: UUID, *, analysis_id: UUID) -> None:
        """Associate an existing artifact row with an analysis when known."""
