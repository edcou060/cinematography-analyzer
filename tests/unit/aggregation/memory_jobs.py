"""In-memory JobRepository for lease races and API unit tests."""

from datetime import datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import (
    AnalysisState,
    IllegalStateTransitionError,
    StageState,
    transition_analysis,
)
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

__all__ = ["MemoryJobRepository"]


def _error(message: str) -> AdapterError:
    return AdapterError("RESOURCE_STATE", message, retryable=False, stage="control")


class MemoryJobRepository:
    """Compare-and-set leases without PostgreSQL."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._videos_by_hash: dict[str, VideoRecord] = {}
        self._videos_by_id: dict[UUID, VideoRecord] = {}
        self._jobs: dict[UUID, AnalysisJob] = {}
        self._jobs_by_key: dict[str, UUID] = {}
        self._identity: dict[tuple[UUID, str, str], UUID] = {}
        self._stages: dict[UUID, StageRunRecord] = {}
        self._artifacts: dict[UUID, ArtifactRecord] = {}
        self._artifacts_by_key: dict[str, UUID] = {}
        self._shots: dict[UUID, ShotIntervalRecord] = {}
        self._summaries: dict[UUID, ReportSummaryRecord] = {}
        self._critiques: list[CritiqueRunRecord] = []
        self.fail_reads = False

    def ping(self) -> None:
        if self.fail_reads:
            raise _error("the database is not reachable")

    def count_inflight(self) -> int:
        self._raise_if_failed()
        inflight = {
            AnalysisState.QUEUED,
            AnalysisState.RUNNING,
            AnalysisState.CANCEL_REQUESTED,
        }
        return sum(1 for job in self._jobs.values() if job.record.state in inflight)

    def close(self) -> None:
        return

    def get_video_by_hash(self, content_sha256: str) -> VideoRecord | None:
        self._raise_if_failed()
        return self._videos_by_hash.get(content_sha256)

    def get_video(self, video_id: UUID) -> VideoRecord | None:
        self._raise_if_failed()
        return self._videos_by_id.get(video_id)

    def insert_video(self, record: VideoRecord) -> VideoRecord:
        with self._lock:
            existing = self._videos_by_hash.get(record.metadata.content_sha256)
            if existing is not None:
                return existing
            if record.metadata.video_id in self._videos_by_id:
                raise _error("state rejected a video insert")
            self._videos_by_hash[record.metadata.content_sha256] = record
            self._videos_by_id[record.metadata.video_id] = record
            return record

    def get_analysis_by_key(self, analysis_key: str) -> AnalysisRecord | None:
        self._raise_if_failed()
        analysis_id = self._jobs_by_key.get(analysis_key)
        if analysis_id is None:
            return None
        return self._jobs[analysis_id].record

    def get_analysis(self, analysis_id: UUID) -> AnalysisRecord | None:
        self._raise_if_failed()
        job = self._jobs.get(analysis_id)
        return None if job is None else job.record

    def insert_analysis(self, record: AnalysisRecord) -> AnalysisRecord:
        with self._lock:
            existing_id = self._jobs_by_key.get(record.analysis_key)
            if existing_id is not None:
                return self._jobs[existing_id].record
            identity = (record.video_id, record.configuration_hash, record.pipeline_version)
            if identity in self._identity:
                raise _error("state rejected an analysis insert")
            job = AnalysisJob(
                record=record,
                progress=0.0,
                config=AnalysisConfig(),
                failure_code=None,
                failure_message=None,
                report_artifact_id=None,
                timeline_artifact_id=None,
            )
            self._jobs[record.analysis_id] = job
            self._jobs_by_key[record.analysis_key] = record.analysis_id
            self._identity[identity] = record.analysis_id
            return record

    def insert_artifact(self, ref: ArtifactRef, *, storage_key: str) -> None:
        with self._lock:
            if storage_key in self._artifacts_by_key:
                return
            record = ArtifactRecord(
                artifact_id=ref.artifact_id,
                kind=ref.kind,
                media_type=ref.media_type,
                sha256=ref.sha256,
                size_bytes=ref.size_bytes,
                storage_key=storage_key,
                analysis_id=None,
            )
            self._artifacts[ref.artifact_id] = record
            self._artifacts_by_key[storage_key] = ref.artifact_id

    def load_job(self, analysis_id: UUID) -> AnalysisJob | None:
        self._raise_if_failed()
        return self._jobs.get(analysis_id)

    def record_config(self, analysis_id: UUID, config: AnalysisConfig) -> None:
        with self._lock:
            job = self._jobs[analysis_id]
            self._jobs[analysis_id] = AnalysisJob(
                record=job.record,
                progress=job.progress,
                config=config,
                failure_code=job.failure_code,
                failure_message=job.failure_message,
                report_artifact_id=job.report_artifact_id,
                timeline_artifact_id=job.timeline_artifact_id,
            )

    def ensure_pending_stages(
        self, analysis_id: UUID, stage_names: tuple[str, ...] = PIPELINE_STAGES
    ) -> None:
        with self._lock:
            for name in stage_names:
                if any(
                    run.analysis_id == analysis_id and run.stage_name == name and run.attempt == 1
                    for run in self._stages.values()
                ):
                    continue
                run_id = uuid4()
                self._stages[run_id] = StageRunRecord(
                    stage_run_id=run_id,
                    analysis_id=analysis_id,
                    stage_name=name,
                    attempt=1,
                    state=StageState.PENDING,
                    lease_token=None,
                    worker_id=None,
                    lease_expires_at=None,
                    error_code=None,
                    error_message=None,
                )

    def list_stage_runs(self, analysis_id: UUID) -> tuple[StageRunRecord, ...]:
        self._raise_if_failed()
        rows = [run for run in self._stages.values() if run.analysis_id == analysis_id]
        return tuple(sorted(rows, key=lambda run: (run.stage_name, run.attempt)))

    def claim_queued(self, *, worker_id: str, now: datetime) -> AnalysisRecord | None:
        if worker_id == "":
            raise _error("worker identity is required")
        with self._lock:
            candidates = [
                job
                for job in self._jobs.values()
                if job.record.state is AnalysisState.QUEUED
                or (
                    job.record.state in {AnalysisState.RUNNING, AnalysisState.CANCEL_REQUESTED}
                    and not self._has_active_lease(job.record.analysis_id, now)
                )
            ]
            if not candidates:
                return None
            job = sorted(candidates, key=lambda item: str(item.record.analysis_id))[0]
            if job.record.state is AnalysisState.QUEUED:
                record = AnalysisRecord(
                    analysis_id=job.record.analysis_id,
                    video_id=job.record.video_id,
                    configuration_hash=job.record.configuration_hash,
                    pipeline_version=job.record.pipeline_version,
                    analysis_key=job.record.analysis_key,
                    state=AnalysisState.RUNNING,
                )
                self._jobs[job.record.analysis_id] = AnalysisJob(
                    record=record,
                    progress=job.progress,
                    config=job.config,
                    failure_code=job.failure_code,
                    failure_message=job.failure_message,
                    report_artifact_id=job.report_artifact_id,
                    timeline_artifact_id=job.timeline_artifact_id,
                )
                return record
            return job.record

    def request_cancel(self, analysis_id: UUID, *, now: datetime) -> AnalysisRecord | None:
        _ = now
        with self._lock:
            job = self._jobs.get(analysis_id)
            if job is None:
                return None
            current = job.record.state
            target = current
            if current is AnalysisState.QUEUED:
                target = AnalysisState.CANCELED
            elif current is AnalysisState.RUNNING:
                target = AnalysisState.CANCEL_REQUESTED
            record = AnalysisRecord(
                analysis_id=job.record.analysis_id,
                video_id=job.record.video_id,
                configuration_hash=job.record.configuration_hash,
                pipeline_version=job.record.pipeline_version,
                analysis_key=job.record.analysis_key,
                state=target,
            )
            self._jobs[analysis_id] = AnalysisJob(
                record=record,
                progress=job.progress,
                config=job.config,
                failure_code=job.failure_code,
                failure_message=job.failure_message,
                report_artifact_id=job.report_artifact_id,
                timeline_artifact_id=job.timeline_artifact_id,
            )
            return record

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
        try:
            transition_analysis(expected, target)
        except IllegalStateTransitionError:
            return False
        with self._lock:
            job = self._jobs.get(analysis_id)
            if job is None or job.record.state is not expected:
                return False
            record = AnalysisRecord(
                analysis_id=job.record.analysis_id,
                video_id=job.record.video_id,
                configuration_hash=job.record.configuration_hash,
                pipeline_version=job.record.pipeline_version,
                analysis_key=job.record.analysis_key,
                state=target,
            )
            self._jobs[analysis_id] = AnalysisJob(
                record=record,
                progress=job.progress if progress is None else progress,
                config=job.config,
                failure_code=job.failure_code if failure_code is None else failure_code,
                failure_message=job.failure_message if failure_message is None else failure_message,
                report_artifact_id=(
                    job.report_artifact_id if report_artifact_id is None else report_artifact_id
                ),
                timeline_artifact_id=(
                    job.timeline_artifact_id
                    if timeline_artifact_id is None
                    else timeline_artifact_id
                ),
            )
            return True

    def acquire_stage(
        self,
        analysis_id: UUID,
        stage_name: str,
        *,
        worker_id: str,
        ttl_ms: int,
        now: datetime,
    ) -> StageLease | None:
        expires = now + timedelta(milliseconds=ttl_ms)
        token = uuid4()
        with self._lock:
            candidates = [
                run
                for run in self._stages.values()
                if run.analysis_id == analysis_id
                and run.stage_name == stage_name
                and (
                    run.state is StageState.PENDING
                    or (
                        run.state in {StageState.LEASED, StageState.RUNNING}
                        and run.lease_expires_at is not None
                        and run.lease_expires_at < now
                    )
                )
            ]
            if not candidates:
                return None
            current = max(candidates, key=lambda run: run.attempt)
            updated = StageRunRecord(
                stage_run_id=current.stage_run_id,
                analysis_id=current.analysis_id,
                stage_name=current.stage_name,
                attempt=current.attempt,
                state=StageState.LEASED,
                lease_token=token,
                worker_id=worker_id,
                lease_expires_at=expires,
                error_code=current.error_code,
                error_message=current.error_message,
            )
            self._stages[current.stage_run_id] = updated
            return StageLease(
                stage_run_id=current.stage_run_id,
                analysis_id=analysis_id,
                stage_name=stage_name,
                attempt=current.attempt,
                token=token,
                worker_id=worker_id,
                expires_at=expires,
            )

    def start_stage(self, lease: StageLease, *, now: datetime) -> bool:
        return self._cas_stage(
            lease, expected=StageState.LEASED, target=StageState.RUNNING, now=now
        )

    def heartbeat_stage(self, lease: StageLease, *, ttl_ms: int, now: datetime) -> bool:
        expires = now + timedelta(milliseconds=ttl_ms)
        with self._lock:
            run = self._stages.get(lease.stage_run_id)
            if (
                run is None
                or run.lease_token != lease.token
                or run.state not in {StageState.LEASED, StageState.RUNNING}
            ):
                return False
            self._stages[lease.stage_run_id] = StageRunRecord(
                stage_run_id=run.stage_run_id,
                analysis_id=run.analysis_id,
                stage_name=run.stage_name,
                attempt=run.attempt,
                state=run.state,
                lease_token=run.lease_token,
                worker_id=run.worker_id,
                lease_expires_at=expires,
                error_code=run.error_code,
                error_message=run.error_message,
            )
            return True

    def complete_stage(self, lease: StageLease, *, now: datetime) -> bool:
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
        target = StageState.FAILED_TERMINAL if terminal else StageState.FAILED_RETRYABLE
        return self._cas_stage(
            lease,
            expected=StageState.RUNNING,
            target=target,
            now=now,
            clear_lease=True,
            error_code=code,
            error_message=message,
        )

    def cancel_stage(self, analysis_id: UUID, stage_name: str, attempt: int) -> bool:
        with self._lock:
            for run_id, run in list(self._stages.items()):
                if (
                    run.analysis_id == analysis_id
                    and run.stage_name == stage_name
                    and run.attempt == attempt
                    and run.state in {StageState.PENDING, StageState.LEASED, StageState.RUNNING}
                ):
                    self._stages[run_id] = StageRunRecord(
                        stage_run_id=run.stage_run_id,
                        analysis_id=run.analysis_id,
                        stage_name=run.stage_name,
                        attempt=run.attempt,
                        state=StageState.CANCELED,
                        lease_token=None,
                        worker_id=run.worker_id,
                        lease_expires_at=run.lease_expires_at,
                        error_code=run.error_code,
                        error_message=run.error_message,
                    )
                    return True
            return False

    def insert_retry_attempt(self, analysis_id: UUID, stage_name: str) -> StageRunRecord:
        with self._lock:
            attempts = [
                run.attempt
                for run in self._stages.values()
                if run.analysis_id == analysis_id and run.stage_name == stage_name
            ]
            attempt = 1 if not attempts else max(attempts) + 1
            run_id = uuid4()
            record = StageRunRecord(
                stage_run_id=run_id,
                analysis_id=analysis_id,
                stage_name=stage_name,
                attempt=attempt,
                state=StageState.PENDING,
                lease_token=None,
                worker_id=None,
                lease_expires_at=None,
                error_code=None,
                error_message=None,
            )
            self._stages[run_id] = record
            return record

    def get_artifact(self, artifact_id: UUID) -> ArtifactRecord | None:
        self._raise_if_failed()
        return self._artifacts.get(artifact_id)

    def get_artifact_by_storage_key(self, storage_key: str) -> ArtifactRecord | None:
        self._raise_if_failed()
        artifact_id = self._artifacts_by_key.get(storage_key)
        if artifact_id is None:
            return None
        return self._artifacts[artifact_id]

    def save_shots(self, analysis_id: UUID, shots: tuple[ShotIntervalRecord, ...]) -> None:
        with self._lock:
            for shot_id, shot in list(self._shots.items()):
                if shot.analysis_id == analysis_id:
                    del self._shots[shot_id]
            for shot in shots:
                self._shots[shot.shot_id] = shot

    def get_shot(self, analysis_id: UUID, shot_id: UUID) -> ShotIntervalRecord | None:
        shot = self._shots.get(shot_id)
        if shot is None or shot.analysis_id != analysis_id:
            return None
        return shot

    def save_report_summary(self, record: ReportSummaryRecord) -> None:
        self._summaries[record.analysis_id] = record

    def get_report_summary(self, analysis_id: UUID) -> ReportSummaryRecord | None:
        return self._summaries.get(analysis_id)

    def save_critique(self, record: CritiqueRunRecord) -> None:
        self._raise_if_failed()
        self._critiques.append(record)

    def get_latest_critique(self, analysis_id: UUID) -> CritiqueRunRecord | None:
        self._raise_if_failed()
        matches = [row for row in self._critiques if row.analysis_id == analysis_id]
        if not matches:
            return None
        return matches[-1]

    def get_critique_by_identity(
        self,
        analysis_id: UUID,
        *,
        prompt_version: str,
        model_name: str,
        input_report_sha256: str,
    ) -> CritiqueRunRecord | None:
        self._raise_if_failed()
        matches = [
            row
            for row in self._critiques
            if row.analysis_id == analysis_id
            and row.critique.prompt_version == prompt_version
            and row.critique.model_name == model_name
            and row.critique.input_report_sha256 == input_report_sha256
        ]
        if not matches:
            return None
        return matches[-1]

    def link_artifact(self, artifact_id: UUID, *, analysis_id: UUID) -> None:
        current = self._artifacts.get(artifact_id)
        if current is None:
            return
        self._artifacts[artifact_id] = ArtifactRecord(
            artifact_id=current.artifact_id,
            kind=current.kind,
            media_type=current.media_type,
            sha256=current.sha256,
            size_bytes=current.size_bytes,
            storage_key=current.storage_key,
            analysis_id=analysis_id,
        )

    def _cas_stage(
        self,
        lease: StageLease,
        *,
        expected: StageState,
        target: StageState,
        now: datetime,
        clear_lease: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        _ = now
        with self._lock:
            run = self._stages.get(lease.stage_run_id)
            if run is None or run.lease_token != lease.token or run.state is not expected:
                return False
            self._stages[lease.stage_run_id] = StageRunRecord(
                stage_run_id=run.stage_run_id,
                analysis_id=run.analysis_id,
                stage_name=run.stage_name,
                attempt=run.attempt,
                state=target,
                lease_token=None if clear_lease else run.lease_token,
                worker_id=run.worker_id,
                lease_expires_at=run.lease_expires_at,
                error_code=run.error_code if error_code is None else error_code,
                error_message=run.error_message if error_message is None else error_message,
            )
            return True

    def _has_active_lease(self, analysis_id: UUID, now: datetime) -> bool:
        return any(
            run.analysis_id == analysis_id
            and run.state in {StageState.LEASED, StageState.RUNNING}
            and run.lease_expires_at is not None
            and run.lease_expires_at >= now
            for run in self._stages.values()
        )

    def _raise_if_failed(self) -> None:
        if self.fail_reads:
            raise _error("state could not be read")
