"""SQLAlchemy 2.0 tables for PostgreSQL. Domain code never imports this module."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["Base", "metadata"]

_ANALYSIS_STATES = (
    "QUEUED",
    "RUNNING",
    "CANCEL_REQUESTED",
    "CANCELED",
    "SUCCEEDED",
    "PARTIAL",
    "FAILED",
)
_STAGE_STATES = (
    "PENDING",
    "LEASED",
    "RUNNING",
    "SUCCEEDED",
    "SKIPPED",
    "FAILED_RETRYABLE",
    "FAILED_TERMINAL",
    "CANCELED",
)


class Base(DeclarativeBase):
    """Declarative base for Alembic and the PostgreSQL adapter."""


metadata = Base.metadata


class VideoRow(Base):
    """Content-addressed video identity."""

    __tablename__ = "videos"

    video_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    probe_storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_videos_created_at", "created_at"),)


class ArtifactRow(Base):
    """Immutable blob metadata. Bytes live in the artifact store."""

    __tablename__ = "artifacts"

    artifact_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str | None] = mapped_column(String(32))
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    analysis_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analyses.analysis_id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (CheckConstraint("size_bytes >= 0", name="ck_artifacts_size"),)


class AnalysisRow(Base):
    """One analysis identity. Config JSON is the hashed snapshot, not secrets."""

    __tablename__ = "analyses"

    analysis_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    video_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("videos.video_id"), nullable=False
    )
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    config_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(512))
    report_artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.artifact_id", use_alter=True, name="fk_analyses_report_artifact"),
    )
    timeline_artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.artifact_id", use_alter=True, name="fk_analyses_timeline_artifact"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "configuration_hash",
            "pipeline_version",
            name="uq_analyses_identity",
        ),
        CheckConstraint(
            "state IN ('" + "','".join(_ANALYSIS_STATES) + "')",
            name="ck_analyses_state",
        ),
        CheckConstraint("progress >= 0 AND progress <= 1", name="ck_analyses_progress"),
        Index("ix_analyses_state_created", "state", "created_at"),
    )


class StageRunRow(Base):
    """One attempt of a leased stage. Completion requires the current token."""

    __tablename__ = "stage_runs"

    stage_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analyses.analysis_id"), nullable=False
    )
    stage_name: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_token: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("analysis_id", "stage_name", "attempt", name="uq_stage_runs_attempt"),
        CheckConstraint("attempt >= 1", name="ck_stage_runs_attempt"),
        CheckConstraint(
            "state IN ('" + "','".join(_STAGE_STATES) + "')",
            name="ck_stage_runs_state",
        ),
        Index(
            "uq_stage_runs_success",
            "analysis_id",
            "stage_name",
            unique=True,
            postgresql_where=text("state = 'SUCCEEDED'"),
        ),
    )


class ShotRow(Base):
    """Shot intervals copied from the validated ShotSet."""

    __tablename__ = "shots"

    shot_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analyses.analysis_id"), nullable=False
    )
    shot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("analysis_id", "shot_index", name="uq_shots_index"),
        CheckConstraint("end_ms > start_ms", name="ck_shots_range"),
        CheckConstraint("shot_index >= 0", name="ck_shots_index"),
        CheckConstraint("start_ms >= 0", name="ck_shots_start"),
    )


class ReportSummaryRow(Base):
    """Small header for status/list views. Canonical JSON is an artifact."""

    __tablename__ = "report_summaries"

    analysis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analyses.analysis_id"), primary_key=True
    )
    shot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    average_shot_length_ms: Mapped[float] = mapped_column(Float, nullable=False)
    median_shot_length_ms: Mapped[float] = mapped_column(Float, nullable=False)
    shots_per_minute: Mapped[float] = mapped_column(Float, nullable=False)
    availability_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    report_artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("artifacts.artifact_id"), nullable=False
    )
    timeline_artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("artifacts.artifact_id")
    )

    __table_args__ = (CheckConstraint("shot_count >= 1", name="ck_report_shot_count"),)


class CritiqueRunRow(Base):
    """Optional interpretation keyed to an analysis and the report digest it read."""

    __tablename__ = "critique_runs"

    critique_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("analyses.analysis_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    input_report_sha256: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
