"""PostgreSQL job repository with compare-and-set leases (ADR-0018)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, create_engine, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, Result
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from cine_analyzer.adapters.persistence.tables import (
    AnalysisRow,
    ArtifactRow,
    CritiqueRunRow,
    ReportSummaryRow,
    ShotRow,
    StageRunRow,
    VideoRow,
)
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import (
    AnalysisState,
    IllegalStateTransitionError,
    StageState,
    analysis_is_terminal,
    transition_analysis,
)
from cine_analyzer.domain.media import VideoMetadata
from cine_analyzer.domain.report import Critique, ReportAvailability, VideoSummary
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.control import (
    PIPELINE_STAGES,
    AnalysisJob,
    ArtifactRecord,
    CritiqueRunRecord,
    ReportSummaryRecord,
    ShotIntervalRecord,
    StageLease,
    StageRunRecord,
)
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord

__all__ = ["PostgresJobRepository"]


def _error(message: str, *, retryable: bool) -> AdapterError:
    return AdapterError("RESOURCE_STATE", message, retryable=retryable, stage="control")


def _updated_one(result: Result[Any]) -> bool:
    """True when a DML statement changed exactly one row."""
    return int(getattr(result, "rowcount", 0)) == 1


class PostgresJobRepository:
    """Authoritative videos, analyses, leases, and report metadata."""

    def __init__(self, database_url: str, *, engine: Engine | None = None) -> None:
        self._engine = engine or create_engine(database_url, pool_pre_ping=True)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def ping(self) -> None:
        """Fail if the database is not reachable."""
        try:
            with self._engine.connect() as connection:
                connection.execute(select(1))
        except SQLAlchemyError as error:
            raise _error("the database is not reachable", retryable=True) from error

    def count_inflight(self) -> int:
        """Count analyses in QUEUED, RUNNING, or CANCEL_REQUESTED."""
        inflight = (
            AnalysisState.QUEUED.value,
            AnalysisState.RUNNING.value,
            AnalysisState.CANCEL_REQUESTED.value,
        )
        try:
            with self._sessions() as session:
                value = session.scalar(
                    select(func.count())
                    .select_from(AnalysisRow)
                    .where(AnalysisRow.state.in_(inflight))
                )
                return int(value or 0)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def close(self) -> None:
        """Release the engine pool."""
        self._engine.dispose()

    def get_video_by_hash(self, content_sha256: str) -> VideoRecord | None:
        """Return the existing video for this content digest, if any."""
        try:
            with self._sessions() as session:
                row = session.scalar(
                    select(VideoRow).where(VideoRow.content_sha256 == content_sha256)
                )
                return None if row is None else _video_from_row(row)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def get_video(self, video_id: UUID) -> VideoRecord | None:
        """Primary-key video lookup."""
        try:
            with self._sessions() as session:
                row = session.get(VideoRow, video_id)
                return None if row is None else _video_from_row(row)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def insert_video(self, record: VideoRecord) -> VideoRecord:
        """Insert, or return the unique row if this content hash already exists."""
        now = datetime.now(tz=UTC)
        row = VideoRow(
            video_id=record.metadata.video_id,
            content_sha256=record.metadata.content_sha256,
            original_storage_key=record.original_storage_key,
            probe_storage_key=record.probe_storage_key,
            metadata_json=record.metadata.model_dump(mode="json"),
            created_at=now,
        )
        with self._sessions() as session:
            try:
                with session.begin():
                    session.add(row)
            except IntegrityError:
                existing = self.get_video_by_hash(record.metadata.content_sha256)
                if existing is None:
                    raise _error("state rejected a video insert", retryable=False) from None
                return existing
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error
        return record

    def get_analysis_by_key(self, analysis_key: str) -> AnalysisRecord | None:
        """Return the existing analysis for this identity key, if any."""
        try:
            with self._sessions() as session:
                row = session.scalar(
                    select(AnalysisRow).where(AnalysisRow.analysis_key == analysis_key)
                )
                return None if row is None else _analysis_from_row(row)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def get_analysis(self, analysis_id: UUID) -> AnalysisRecord | None:
        """Primary-key analysis lookup."""
        try:
            with self._sessions() as session:
                row = session.get(AnalysisRow, analysis_id)
                return None if row is None else _analysis_from_row(row)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def insert_analysis(self, record: AnalysisRecord) -> AnalysisRecord:
        """Insert, or return the unique row if this analysis key already exists."""
        now = datetime.now(tz=UTC)
        row = AnalysisRow(
            analysis_id=record.analysis_id,
            video_id=record.video_id,
            configuration_hash=record.configuration_hash,
            pipeline_version=record.pipeline_version,
            analysis_key=record.analysis_key,
            config_json={},
            state=record.state.value,
            progress=0.0,
            created_at=now,
            updated_at=now,
        )
        with self._sessions() as session:
            try:
                with session.begin():
                    session.add(row)
            except IntegrityError:
                existing = self.get_analysis_by_key(record.analysis_key)
                if existing is None:
                    raise _error("state rejected an analysis insert", retryable=False) from None
                return existing
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error
        return record

    def insert_artifact(self, ref: ArtifactRef, *, storage_key: str) -> None:
        """Record metadata for a canonical blob."""
        now = datetime.now(tz=UTC)
        statement = (
            pg_insert(ArtifactRow)
            .values(
                artifact_id=ref.artifact_id,
                kind=ref.kind,
                media_type=ref.media_type,
                sha256=ref.sha256,
                size_bytes=ref.size_bytes,
                schema_version=ref.schema_version,
                storage_key=storage_key,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["storage_key"])
        )
        with self._sessions() as session:
            try:
                with session.begin():
                    session.execute(statement)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def load_job(self, analysis_id: UUID) -> AnalysisJob | None:
        """Analysis row including config snapshot and progress."""
        try:
            with self._sessions() as session:
                row = session.get(AnalysisRow, analysis_id)
                if row is None:
                    return None
                return _job_from_row(row)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def record_config(self, analysis_id: UUID, config: AnalysisConfig) -> None:
        """Persist the hashed config body so a worker can reconstruct it."""
        with self._sessions() as session:
            try:
                with session.begin():
                    session.execute(
                        update(AnalysisRow)
                        .where(AnalysisRow.analysis_id == analysis_id)
                        .values(config_json=config.model_dump(mode="json"))
                    )
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def ensure_pending_stages(
        self, analysis_id: UUID, stage_names: tuple[str, ...] = PIPELINE_STAGES
    ) -> None:
        """Idempotently insert attempt-1 PENDING rows."""
        now = datetime.now(tz=UTC)
        rows = [
            {
                "stage_run_id": uuid4(),
                "analysis_id": analysis_id,
                "stage_name": name,
                "attempt": 1,
                "state": StageState.PENDING.value,
                "created_at": now,
                "updated_at": now,
            }
            for name in stage_names
        ]
        with self._sessions() as session:
            try:
                with session.begin():
                    if not rows:
                        return
                    statement = (
                        pg_insert(StageRunRow)
                        .values(rows)
                        .on_conflict_do_nothing(constraint="uq_stage_runs_attempt")
                    )
                    session.execute(statement)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def list_stage_runs(self, analysis_id: UUID) -> tuple[StageRunRecord, ...]:
        """All attempts for one analysis, ordered by stage then attempt."""
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(StageRunRow)
                    .where(StageRunRow.analysis_id == analysis_id)
                    .order_by(StageRunRow.stage_name, StageRunRow.attempt)
                ).all()
                return tuple(_stage_from_row(row) for row in rows)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def claim_queued(self, *, worker_id: str, now: datetime) -> AnalysisRecord | None:
        """QUEUED → RUNNING for one row, or None if the queue is empty."""
        if worker_id == "":
            raise _error("worker identity is required", retryable=False)
        active_lease = exists(
            select(StageRunRow.stage_run_id).where(
                StageRunRow.analysis_id == AnalysisRow.analysis_id,
                StageRunRow.state.in_((StageState.LEASED.value, StageState.RUNNING.value)),
                StageRunRow.lease_expires_at.is_not(None),
                StageRunRow.lease_expires_at >= now,
            )
        )
        statement: Select[tuple[AnalysisRow]] = (
            select(AnalysisRow)
            .where(
                or_(
                    AnalysisRow.state == AnalysisState.QUEUED.value,
                    and_(
                        AnalysisRow.state == AnalysisState.RUNNING.value,
                        ~active_lease,
                    ),
                    and_(
                        AnalysisRow.state == AnalysisState.CANCEL_REQUESTED.value,
                        ~active_lease,
                    ),
                )
            )
            .order_by(AnalysisRow.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        with self._sessions() as session:
            try:
                with session.begin():
                    row = session.scalar(statement)
                    if row is None:
                        return None
                    if row.state == AnalysisState.QUEUED.value:
                        row.state = AnalysisState.RUNNING.value
                        row.started_at = now
                    row.updated_at = now
                    session.flush()
                    return _analysis_from_row(row)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def request_cancel(self, analysis_id: UUID, *, now: datetime) -> AnalysisRecord | None:
        """Record cooperative cancellation. None if the analysis does not exist."""
        with self._sessions() as session:
            try:
                with session.begin():
                    row = session.get(AnalysisRow, analysis_id)
                    if row is None:
                        return None
                    current = AnalysisState(row.state)
                    if current is AnalysisState.QUEUED:
                        row.state = AnalysisState.CANCELED.value
                        row.completed_at = now
                    elif current is AnalysisState.RUNNING:
                        row.state = AnalysisState.CANCEL_REQUESTED.value
                    row.updated_at = now
                    session.flush()
                    return _analysis_from_row(row)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

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
        try:
            transition_analysis(expected, target)
        except IllegalStateTransitionError:
            return False
        now = datetime.now(tz=UTC)
        values: dict[str, Any] = {"state": target.value, "updated_at": now}
        if progress is not None:
            values["progress"] = progress
        if failure_code is not None:
            values["failure_code"] = failure_code
        if failure_message is not None:
            values["failure_message"] = failure_message
        if report_artifact_id is not None:
            values["report_artifact_id"] = report_artifact_id
        if timeline_artifact_id is not None:
            values["timeline_artifact_id"] = timeline_artifact_id
        if analysis_is_terminal(target):
            values["completed_at"] = now
        if target is AnalysisState.RUNNING:
            values["started_at"] = now
        with self._sessions() as session:
            try:
                with session.begin():
                    result = session.execute(
                        update(AnalysisRow)
                        .where(
                            AnalysisRow.analysis_id == analysis_id,
                            AnalysisRow.state == expected.value,
                        )
                        .values(**values)
                    )
                    return _updated_one(result)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

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
        expires = now + timedelta(milliseconds=ttl_ms)
        token = uuid4()
        claimable = or_(
            StageRunRow.state == StageState.PENDING.value,
            and_(
                StageRunRow.state.in_((StageState.LEASED.value, StageState.RUNNING.value)),
                StageRunRow.lease_expires_at.is_not(None),
                StageRunRow.lease_expires_at < now,
            ),
        )
        with self._sessions() as session:
            try:
                with session.begin():
                    candidate = session.scalar(
                        select(StageRunRow)
                        .where(
                            StageRunRow.analysis_id == analysis_id,
                            StageRunRow.stage_name == stage_name,
                            claimable,
                        )
                        .order_by(StageRunRow.attempt.desc())
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if candidate is None:
                        return None
                    candidate.state = StageState.LEASED.value
                    candidate.lease_token = token
                    candidate.worker_id = worker_id
                    candidate.lease_expires_at = expires
                    candidate.updated_at = now
                    session.flush()
                    return StageLease(
                        stage_run_id=candidate.stage_run_id,
                        analysis_id=analysis_id,
                        stage_name=stage_name,
                        attempt=candidate.attempt,
                        token=token,
                        worker_id=worker_id,
                        expires_at=expires,
                    )
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def start_stage(self, lease: StageLease, *, now: datetime) -> bool:
        """LEASED → RUNNING using the lease token."""
        return self._cas_stage(
            lease,
            expected=StageState.LEASED,
            target=StageState.RUNNING,
            now=now,
        )

    def heartbeat_stage(self, lease: StageLease, *, ttl_ms: int, now: datetime) -> bool:
        """Extend expiry. False if the token no longer matches."""
        expires = now + timedelta(milliseconds=ttl_ms)
        with self._sessions() as session:
            try:
                with session.begin():
                    result = session.execute(
                        update(StageRunRow)
                        .where(
                            StageRunRow.stage_run_id == lease.stage_run_id,
                            StageRunRow.lease_token == lease.token,
                            StageRunRow.state.in_(
                                (StageState.LEASED.value, StageState.RUNNING.value)
                            ),
                        )
                        .values(lease_expires_at=expires, updated_at=now)
                    )
                    return _updated_one(result)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def complete_stage(self, lease: StageLease, *, now: datetime) -> bool:
        """RUNNING → SUCCEEDED using the lease token."""
        return self._cas_stage(
            lease,
            expected=StageState.RUNNING,
            target=StageState.SUCCEEDED,
            now=now,
            clear_lease=True,
        )

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
        target = StageState.FAILED_TERMINAL if terminal else StageState.FAILED_RETRYABLE
        return self._cas_stage(
            lease,
            expected=StageState.RUNNING,
            target=target,
            now=now,
            clear_lease=True,
            extra={"error_code": code, "error_message": message, "retryable": not terminal},
        )

    def cancel_stage(self, analysis_id: UUID, stage_name: str, attempt: int) -> bool:
        """PENDING/LEASED/RUNNING → CANCELED for an attempt."""
        now = datetime.now(tz=UTC)
        with self._sessions() as session:
            try:
                with session.begin():
                    result = session.execute(
                        update(StageRunRow)
                        .where(
                            StageRunRow.analysis_id == analysis_id,
                            StageRunRow.stage_name == stage_name,
                            StageRunRow.attempt == attempt,
                            StageRunRow.state.in_(
                                (
                                    StageState.PENDING.value,
                                    StageState.LEASED.value,
                                    StageState.RUNNING.value,
                                )
                            ),
                        )
                        .values(
                            state=StageState.CANCELED.value,
                            lease_token=None,
                            updated_at=now,
                        )
                    )
                    return _updated_one(result)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def insert_retry_attempt(self, analysis_id: UUID, stage_name: str) -> StageRunRecord:
        """Allocate the next PENDING attempt after FAILED_RETRYABLE."""
        now = datetime.now(tz=UTC)
        with self._sessions() as session:
            try:
                with session.begin():
                    current = session.scalar(
                        select(func.max(StageRunRow.attempt)).where(
                            StageRunRow.analysis_id == analysis_id,
                            StageRunRow.stage_name == stage_name,
                        )
                    )
                    attempt = 1 if current is None else int(current) + 1
                    row = StageRunRow(
                        stage_run_id=uuid4(),
                        analysis_id=analysis_id,
                        stage_name=stage_name,
                        attempt=attempt,
                        state=StageState.PENDING.value,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    session.flush()
                    return _stage_from_row(row)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def get_artifact(self, artifact_id: UUID) -> ArtifactRecord | None:
        """Authorize an artifact stream by id."""
        try:
            with self._sessions() as session:
                row = session.get(ArtifactRow, artifact_id)
                if row is None:
                    return None
                return _artifact_from_row(row)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def get_artifact_by_storage_key(self, storage_key: str) -> ArtifactRecord | None:
        """Look up artifact metadata by canonical storage key."""
        try:
            with self._sessions() as session:
                row = session.scalar(
                    select(ArtifactRow).where(ArtifactRow.storage_key == storage_key)
                )
                if row is None:
                    return None
                return _artifact_from_row(row)
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def save_shots(self, analysis_id: UUID, shots: tuple[ShotIntervalRecord, ...]) -> None:
        """Replace shot intervals for one analysis."""
        with self._sessions() as session:
            try:
                with session.begin():
                    session.execute(delete(ShotRow).where(ShotRow.analysis_id == analysis_id))
                    for shot in shots:
                        session.add(
                            ShotRow(
                                shot_id=shot.shot_id,
                                analysis_id=analysis_id,
                                shot_index=shot.shot_index,
                                start_ms=shot.start_ms,
                                end_ms=shot.end_ms,
                            )
                        )
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def get_shot(self, analysis_id: UUID, shot_id: UUID) -> ShotIntervalRecord | None:
        """One shot interval, or None."""
        try:
            with self._sessions() as session:
                row = session.get(ShotRow, shot_id)
                if row is None or row.analysis_id != analysis_id:
                    return None
                return ShotIntervalRecord(
                    shot_id=row.shot_id,
                    analysis_id=row.analysis_id,
                    shot_index=row.shot_index,
                    start_ms=row.start_ms,
                    end_ms=row.end_ms,
                )
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def save_report_summary(self, record: ReportSummaryRecord) -> None:
        """Upsert the small report header."""
        payload = {
            "analysis_id": record.analysis_id,
            "shot_count": record.summary.shot_count,
            "average_shot_length_ms": record.summary.average_shot_length_ms,
            "median_shot_length_ms": record.summary.median_shot_length_ms,
            "shots_per_minute": record.summary.shots_per_minute,
            "availability_json": record.availability.model_dump(mode="json"),
            "report_artifact_id": record.report_artifact_id,
            "timeline_artifact_id": record.timeline_artifact_id,
        }
        statement = pg_insert(ReportSummaryRow).values(**payload)
        statement = statement.on_conflict_do_update(
            index_elements=["analysis_id"],
            set_={key: statement.excluded[key] for key in payload if key != "analysis_id"},
        )
        with self._sessions() as session:
            try:
                with session.begin():
                    session.execute(statement)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def get_report_summary(self, analysis_id: UUID) -> ReportSummaryRecord | None:
        """Saved summary, or None if aggregation has not run."""
        try:
            with self._sessions() as session:
                row = session.get(ReportSummaryRow, analysis_id)
                if row is None:
                    return None
                return ReportSummaryRecord(
                    analysis_id=row.analysis_id,
                    summary=VideoSummary(
                        shot_count=row.shot_count,
                        average_shot_length_ms=row.average_shot_length_ms,
                        median_shot_length_ms=row.median_shot_length_ms,
                        shots_per_minute=row.shots_per_minute,
                    ),
                    availability=ReportAvailability.model_validate(row.availability_json),
                    report_artifact_id=row.report_artifact_id,
                    timeline_artifact_id=row.timeline_artifact_id,
                )
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def save_critique(self, record: CritiqueRunRecord) -> None:
        """Insert a critique row."""
        with self._sessions() as session:
            try:
                with session.begin():
                    session.add(
                        CritiqueRunRow(
                            critique_run_id=record.critique_run_id,
                            analysis_id=record.analysis_id,
                            status=record.critique.status.value,
                            prompt_version=record.critique.prompt_version,
                            model_name=record.critique.model_name,
                            input_report_sha256=record.critique.input_report_sha256,
                            text=record.critique.text,
                            created_at=record.created_at,
                        )
                    )
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def get_latest_critique(self, analysis_id: UUID) -> CritiqueRunRecord | None:
        """Newest critique for an analysis, or None."""
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(CritiqueRunRow)
                    .where(CritiqueRunRow.analysis_id == analysis_id)
                    .order_by(CritiqueRunRow.created_at.desc())
                ).all()
                if not rows:
                    return None
                return _critique_from_row(rows[0])
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def get_critique_by_identity(
        self,
        analysis_id: UUID,
        *,
        prompt_version: str,
        model_name: str,
        input_report_sha256: str,
    ) -> CritiqueRunRecord | None:
        """Idempotent lookup for the same prompt, model, and report digest."""
        try:
            with self._sessions() as session:
                rows = session.scalars(
                    select(CritiqueRunRow)
                    .where(
                        CritiqueRunRow.analysis_id == analysis_id,
                        CritiqueRunRow.prompt_version == prompt_version,
                        CritiqueRunRow.model_name == model_name,
                        CritiqueRunRow.input_report_sha256 == input_report_sha256,
                    )
                    .order_by(CritiqueRunRow.created_at.desc())
                ).all()
                if not rows:
                    return None
                return _critique_from_row(rows[0])
        except SQLAlchemyError as error:
            raise _error("state could not be read", retryable=True) from error

    def link_artifact(self, artifact_id: UUID, *, analysis_id: UUID) -> None:
        """Associate an existing artifact row with an analysis when known."""
        with self._sessions() as session:
            try:
                with session.begin():
                    session.execute(
                        update(ArtifactRow)
                        .where(ArtifactRow.artifact_id == artifact_id)
                        .values(analysis_id=analysis_id)
                    )
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error

    def _cas_stage(
        self,
        lease: StageLease,
        *,
        expected: StageState,
        target: StageState,
        now: datetime,
        clear_lease: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        values: dict[str, Any] = {"state": target.value, "updated_at": now}
        if clear_lease:
            values["lease_token"] = None
        if extra:
            values.update(extra)
        with self._sessions() as session:
            try:
                with session.begin():
                    result = session.execute(
                        update(StageRunRow)
                        .where(
                            StageRunRow.stage_run_id == lease.stage_run_id,
                            StageRunRow.lease_token == lease.token,
                            StageRunRow.state == expected.value,
                        )
                        .values(**values)
                    )
                    return _updated_one(result)
            except SQLAlchemyError as error:
                raise _error("state could not be written", retryable=True) from error


def _artifact_from_row(row: ArtifactRow) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=row.artifact_id,
        kind=row.kind,
        media_type=row.media_type,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        storage_key=row.storage_key,
        analysis_id=row.analysis_id,
    )


def _video_from_row(row: VideoRow) -> VideoRecord:
    return VideoRecord(
        metadata=VideoMetadata.model_validate(row.metadata_json),
        original_storage_key=row.original_storage_key,
        probe_storage_key=row.probe_storage_key,
    )


def _analysis_from_row(row: AnalysisRow) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=row.analysis_id,
        video_id=row.video_id,
        configuration_hash=row.configuration_hash,
        pipeline_version=row.pipeline_version,
        analysis_key=row.analysis_key,
        state=AnalysisState(row.state),
    )


def _job_from_row(row: AnalysisRow) -> AnalysisJob:
    payload = row.config_json or {}
    config = AnalysisConfig() if payload == {} else AnalysisConfig.model_validate(payload)
    return AnalysisJob(
        record=_analysis_from_row(row),
        progress=row.progress,
        config=config,
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        report_artifact_id=row.report_artifact_id,
        timeline_artifact_id=row.timeline_artifact_id,
    )


def _stage_from_row(row: StageRunRow) -> StageRunRecord:
    return StageRunRecord(
        stage_run_id=row.stage_run_id,
        analysis_id=row.analysis_id,
        stage_name=row.stage_name,
        attempt=row.attempt,
        state=StageState(row.state),
        lease_token=row.lease_token,
        worker_id=row.worker_id,
        lease_expires_at=row.lease_expires_at,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _critique_from_row(row: CritiqueRunRow) -> CritiqueRunRecord:
    return CritiqueRunRecord(
        critique_run_id=row.critique_run_id,
        analysis_id=row.analysis_id,
        critique=Critique(
            status=MetricStatus(row.status),
            text=row.text,
            model_name=row.model_name,
            prompt_version=row.prompt_version,
            input_report_sha256=row.input_report_sha256,
        ),
        created_at=row.created_at,
    )
