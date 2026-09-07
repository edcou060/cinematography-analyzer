"""Initial PostgreSQL control-plane schema.

Revision ID: 20260906_0018
Revises:
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0018"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

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


def upgrade() -> None:
    """Create core tables. Do not use metadata.create_all at runtime."""
    op.create_table(
        "videos",
        sa.Column("video_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("original_storage_key", sa.Text(), nullable=False),
        sa.Column("probe_storage_key", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_videos_created_at", "videos", ["created_at"])
    op.create_table(
        "analyses",
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "video_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("videos.video_id"),
            nullable=False,
        ),
        sa.Column("configuration_hash", sa.String(64), nullable=False),
        sa.Column("pipeline_version", sa.String(64), nullable=False),
        sa.Column("analysis_key", sa.String(64), nullable=False, unique=True),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("failure_message", sa.String(512)),
        sa.Column("report_artifact_id", postgresql.UUID(as_uuid=True)),
        sa.Column("timeline_artifact_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "video_id",
            "configuration_hash",
            "pipeline_version",
            name="uq_analyses_identity",
        ),
        sa.CheckConstraint(
            "state IN ('" + "','".join(_ANALYSIS_STATES) + "')",
            name="ck_analyses_state",
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_analyses_progress"),
    )
    op.create_index("ix_analyses_state_created", "analyses", ["state", "created_at"])
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32)),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.analysis_id"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifacts_size"),
    )
    op.create_foreign_key(
        "fk_analyses_report_artifact",
        "analyses",
        "artifacts",
        ["report_artifact_id"],
        ["artifact_id"],
    )
    op.create_foreign_key(
        "fk_analyses_timeline_artifact",
        "analyses",
        "artifacts",
        ["timeline_artifact_id"],
        ["artifact_id"],
    )
    op.create_table(
        "stage_runs",
        sa.Column("stage_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.analysis_id"),
            nullable=False,
        ),
        sa.Column("stage_name", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.String(512)),
        sa.Column("retryable", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "stage_name", "attempt", name="uq_stage_runs_attempt"),
        sa.CheckConstraint("attempt >= 1", name="ck_stage_runs_attempt"),
        sa.CheckConstraint(
            "state IN ('" + "','".join(_STAGE_STATES) + "')",
            name="ck_stage_runs_state",
        ),
    )
    op.create_index(
        "uq_stage_runs_success",
        "stage_runs",
        ["analysis_id", "stage_name"],
        unique=True,
        postgresql_where=sa.text("state = 'SUCCEEDED'"),
    )
    op.create_table(
        "shots",
        sa.Column("shot_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.analysis_id"),
            nullable=False,
        ),
        sa.Column("shot_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.UniqueConstraint("analysis_id", "shot_index", name="uq_shots_index"),
        sa.CheckConstraint("end_ms > start_ms", name="ck_shots_range"),
        sa.CheckConstraint("shot_index >= 0", name="ck_shots_index"),
        sa.CheckConstraint("start_ms >= 0", name="ck_shots_start"),
    )
    op.create_table(
        "report_summaries",
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.analysis_id"),
            primary_key=True,
        ),
        sa.Column("shot_count", sa.Integer(), nullable=False),
        sa.Column("average_shot_length_ms", sa.Float(), nullable=False),
        sa.Column("median_shot_length_ms", sa.Float(), nullable=False),
        sa.Column("shots_per_minute", sa.Float(), nullable=False),
        sa.Column("availability_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "report_artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.artifact_id"),
            nullable=False,
        ),
        sa.Column(
            "timeline_artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.artifact_id"),
        ),
        sa.CheckConstraint("shot_count >= 1", name="ck_report_shot_count"),
    )
    op.create_table(
        "critique_runs",
        sa.Column("critique_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.analysis_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column("model_name", sa.String(128)),
        sa.Column("input_report_sha256", sa.String(64)),
        sa.Column("text", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop control-plane tables."""
    op.drop_table("critique_runs")
    op.drop_table("report_summaries")
    op.drop_table("shots")
    op.drop_index("uq_stage_runs_success", table_name="stage_runs")
    op.drop_table("stage_runs")
    op.drop_constraint("fk_analyses_timeline_artifact", "analyses", type_="foreignkey")
    op.drop_constraint("fk_analyses_report_artifact", "analyses", type_="foreignkey")
    op.drop_table("artifacts")
    op.drop_index("ix_analyses_state_created", table_name="analyses")
    op.drop_table("analyses")
    op.drop_index("ix_videos_created_at", table_name="videos")
    op.drop_table("videos")
