"""Application-facing ports. Adapters implement these; domain models do not import them."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.media import VideoMetadata
from cine_analyzer.domain.time import Rational

__all__ = [
    "AnalysisRecord",
    "AnalysisRepository",
    "ArtifactStore",
    "MediaProbe",
    "ProbeFacts",
    "StagingObject",
    "StoredBlob",
    "VideoRecord",
]


@dataclass(frozen=True, slots=True)
class ProbeFacts:
    """Normalised probe facts before identity UUIDs exist."""

    duration_ms: int
    width: int
    height: int
    display_rotation_degrees: int
    average_frame_rate: Rational
    real_frame_rate: Rational | None
    video_codec: str
    pixel_format: str | None
    has_audio: bool
    audio_codec: str | None
    color_transfer: str | None
    video_stream_count: int
    audio_stream_count: int
    raw_json: bytes


@dataclass(frozen=True, slots=True)
class StoredBlob:
    """Bytes that have been checksummed and promoted to an immutable key."""

    sha256: str
    size_bytes: int
    storage_key: str


class StagingObject(Protocol):
    """A temporary write that is either promoted atomically or discarded."""

    def write(self, chunk: bytes) -> None:
        """Append one chunk and update the running digest."""

    def digest(self) -> str:
        """SHA-256 of bytes written so far."""

    def size_bytes(self) -> int:
        """Count of bytes written so far."""

    def local_path(self) -> Path:
        """Absolute path for probing. Never placed in a queue payload or SafeError."""

    def commit(self, *, storage_key: str) -> StoredBlob:
        """Fsync, checksum, and rename into the canonical key."""

    def abort(self) -> None:
        """Delete this temporary object only."""


class ArtifactStore(Protocol):
    """Immutable blob store. Local paths never leave a client-visible error."""

    def begin_write(self) -> StagingObject:
        """Open a unique temporary object under the tmp prefix."""

    def put_bytes(self, data: bytes, *, storage_key: str) -> StoredBlob:
        """Write a small complete blob such as probe JSON."""

    def open_read(self, storage_key: str) -> Iterator[bytes]:
        """Yield canonical bytes. Unknown keys fail."""

    def contains(self, storage_key: str) -> bool:
        """True when the canonical key already exists."""

    def local_path(self, storage_key: str) -> Path:
        """Absolute path of a canonical blob for decode. Never placed in a SafeError."""

    def put_replaceable(self, data: bytes, *, storage_key: str) -> StoredBlob:
        """Atomically write a stage output that may replace a previous blob at the same key."""


@dataclass(frozen=True, slots=True)
class VideoRecord:
    """Persisted video identity plus the artifact keys that back it."""

    metadata: VideoMetadata
    original_storage_key: str
    probe_storage_key: str


@dataclass(frozen=True, slots=True)
class AnalysisRecord:
    """Persisted analysis identity. Stages are not started here."""

    analysis_id: UUID
    video_id: UUID
    configuration_hash: str
    pipeline_version: str
    analysis_key: str
    state: AnalysisState


class MediaProbe(Protocol):
    """Characterise a local media file. Implementations must not use a shell."""

    def probe(self, path: Path) -> ProbeFacts:
        """Return normalised facts or raise an application ingest error."""


class AnalysisRepository(Protocol):
    """Video/analysis identity for this process.

    The SQLite adapter is a disposable Profile A store. Production state is PostgreSQL.
    """

    def get_video_by_hash(self, content_sha256: str) -> VideoRecord | None:
        """Return the existing video for this content digest, if any."""

    def insert_video(self, record: VideoRecord) -> VideoRecord:
        """Insert, or return the unique row if this content hash already exists."""

    def get_analysis_by_key(self, analysis_key: str) -> AnalysisRecord | None:
        """Return the existing analysis for this identity key, if any."""

    def insert_analysis(self, record: AnalysisRecord) -> AnalysisRecord:
        """Insert, or return the unique row if this analysis key already exists."""

    def insert_artifact(self, ref: ArtifactRef, *, storage_key: str) -> None:
        """Record metadata for a canonical blob."""
