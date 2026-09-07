"""Disposable SQLite repository for Profile A.

PostgreSQL remains the production system of record (ADR-0003). This adapter is
a local/demo store: schema is applied with CREATE TABLE IF NOT EXISTS on connect,
and the file is safe to delete. It is not a migration path.
"""

import sqlite3
from pathlib import Path
from uuid import UUID

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.media import VideoMetadata
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord

__all__ = ["SCHEMA_SQL", "SqliteAnalysisRepository"]

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL UNIQUE,
    original_storage_key TEXT NOT NULL,
    probe_storage_key TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    analysis_id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos (video_id),
    configuration_hash TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    analysis_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    UNIQUE (video_id, configuration_hash, pipeline_version)
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    schema_version TEXT,
    storage_key TEXT NOT NULL UNIQUE
);
"""


def _error(message: str, *, retryable: bool) -> AdapterError:
    return AdapterError("RESOURCE_STATE", message, retryable=retryable, stage="ingest")


def _rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        return


class SqliteAnalysisRepository:
    """Video/analysis identity for one local SQLite file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(path, timeout=5.0)
            self._connection.row_factory = sqlite3.Row
            self._connection.executescript(SCHEMA_SQL)
            self._connection.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as error:
            raise _error("local state could not be initialised", retryable=True) from error

    def get_video_by_hash(self, content_sha256: str) -> VideoRecord | None:
        """Return the existing video for this content digest, if any."""
        try:
            row = self._connection.execute(
                "SELECT metadata_json, original_storage_key, probe_storage_key "
                "FROM videos WHERE content_sha256 = ?",
                (content_sha256,),
            ).fetchone()
        except sqlite3.Error as error:
            raise _error("local state could not be read", retryable=True) from error
        if row is None:
            return None
        return _video_from_row(row)

    def insert_video(self, record: VideoRecord) -> VideoRecord:
        """Insert, or return the unique row if this content hash already exists."""
        payload = (
            str(record.metadata.video_id),
            record.metadata.content_sha256,
            record.original_storage_key,
            record.probe_storage_key,
            record.metadata.model_dump_json(),
        )
        try:
            self._connection.execute(
                "INSERT INTO videos ("
                "video_id, content_sha256, original_storage_key, probe_storage_key, metadata_json"
                ") VALUES (?, ?, ?, ?, ?)",
                payload,
            )
            self._connection.commit()
        except sqlite3.IntegrityError:
            _rollback(self._connection)
            existing = self.get_video_by_hash(record.metadata.content_sha256)
            if existing is None:
                raise _error("local state rejected a video insert", retryable=False) from None
            return existing
        except sqlite3.Error as error:
            _rollback(self._connection)
            raise _error("local state could not be written", retryable=True) from error
        return record

    def get_analysis_by_key(self, analysis_key: str) -> AnalysisRecord | None:
        """Return the existing analysis for this identity key, if any."""
        try:
            row = self._connection.execute(
                "SELECT analysis_id, video_id, configuration_hash, pipeline_version, "
                "analysis_key, state FROM analyses WHERE analysis_key = ?",
                (analysis_key,),
            ).fetchone()
        except sqlite3.Error as error:
            raise _error("local state could not be read", retryable=True) from error
        if row is None:
            return None
        return _analysis_from_row(row)

    def insert_analysis(self, record: AnalysisRecord) -> AnalysisRecord:
        """Insert, or return the unique row if this analysis key already exists."""
        payload = (
            str(record.analysis_id),
            str(record.video_id),
            record.configuration_hash,
            record.pipeline_version,
            record.analysis_key,
            record.state.value,
        )
        try:
            self._connection.execute(
                "INSERT INTO analyses ("
                "analysis_id, video_id, configuration_hash, pipeline_version, analysis_key, state"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                payload,
            )
            self._connection.commit()
        except sqlite3.IntegrityError:
            _rollback(self._connection)
            existing = self.get_analysis_by_key(record.analysis_key)
            if existing is None:
                raise _error("local state rejected an analysis insert", retryable=False) from None
            return existing
        except sqlite3.Error as error:
            _rollback(self._connection)
            raise _error("local state could not be written", retryable=True) from error
        return record

    def insert_artifact(self, ref: ArtifactRef, *, storage_key: str) -> None:
        """Record metadata for a canonical blob."""
        payload = (
            str(ref.artifact_id),
            ref.kind,
            ref.media_type,
            ref.sha256,
            ref.size_bytes,
            ref.schema_version,
            storage_key,
        )
        try:
            self._connection.execute(
                "INSERT INTO artifacts ("
                "artifact_id, kind, media_type, sha256, size_bytes, schema_version, storage_key"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                payload,
            )
            self._connection.commit()
        except sqlite3.IntegrityError:
            _rollback(self._connection)
        except sqlite3.Error as error:
            _rollback(self._connection)
            raise _error("local state could not be written", retryable=True) from error

    def close(self) -> None:
        """Close the underlying connection. Process exit also releases it."""
        self._connection.close()


def _video_from_row(row: sqlite3.Row) -> VideoRecord:
    return VideoRecord(
        metadata=VideoMetadata.model_validate_json(row["metadata_json"]),
        original_storage_key=row["original_storage_key"],
        probe_storage_key=row["probe_storage_key"],
    )


def _analysis_from_row(row: sqlite3.Row) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=UUID(row["analysis_id"]),
        video_id=UUID(row["video_id"]),
        configuration_hash=row["configuration_hash"],
        pipeline_version=row["pipeline_version"],
        analysis_key=row["analysis_key"],
        state=AnalysisState(row["state"]),
    )
