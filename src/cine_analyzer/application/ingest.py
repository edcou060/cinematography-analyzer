"""Stream, hash, probe, validate, and persist a video identity."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from cine_analyzer.application.errors import AdapterError, ingest_error, wrap_adapter
from cine_analyzer.application.filenames import sanitize_original_filename
from cine_analyzer.application.media_rules import validate_probe_facts
from cine_analyzer.application.resources import ensure_disk_headroom
from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.media import VideoMetadata
from cine_analyzer.domain.types import SCHEMA_VERSION
from cine_analyzer.logging_setup import bind_context, get_logger
from cine_analyzer.ports.ingestion import (
    AnalysisRepository,
    ArtifactStore,
    MediaProbe,
    ProbeFacts,
    StagingObject,
    StoredBlob,
    VideoRecord,
)

__all__ = ["IngestResult", "IngestVideo", "content_storage_key"]


def content_storage_key(digest: str) -> str:
    """Fan-out key for a content-addressed blob. Not a user-supplied path."""
    return f"{digest[:2]}/{digest}"


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of ingest: a video row, and whether it already existed."""

    video: VideoRecord
    reused: bool


class IngestVideo:
    """Local ingest use case. Queue payloads are not constructed here."""

    def __init__(
        self,
        store: ArtifactStore,
        probe: MediaProbe,
        repository: AnalysisRepository,
        *,
        chunk_bytes: int,
        min_free_bytes: int = 0,
    ) -> None:
        self._store = store
        self._probe = probe
        self._repository = repository
        self._chunk_bytes = chunk_bytes
        self._min_free_bytes = min_free_bytes

    def execute(
        self,
        source: Path,
        *,
        original_filename: str,
        config: AnalysisConfig,
        request_id: str,
    ) -> IngestResult:
        """Stream ``source`` into the store, probe it, and persist or reuse identity."""
        with bind_context(request_id=request_id, stage="ingest"):
            try:
                result = self._execute(
                    source,
                    original_filename=original_filename,
                    config=config,
                    request_id=request_id,
                )
            except AdapterError as error:
                raise wrap_adapter(error, request_id=request_id) from error
            get_logger(__name__).info(
                "ingest.completed",
                video_id=str(result.video.metadata.video_id),
                reused=result.reused,
            )
            return result

    def _execute(
        self,
        source: Path,
        *,
        original_filename: str,
        config: AnalysisConfig,
        request_id: str,
    ) -> IngestResult:
        filename = sanitize_original_filename(original_filename)
        ensure_disk_headroom(source, self._min_free_bytes, request_id=request_id)
        staging = self._store.begin_write()
        committed = False
        try:
            self._stream(
                source,
                staging,
                max_bytes=config.limits.max_upload_bytes,
                request_id=request_id,
            )
            digest = staging.digest()
            size_bytes = staging.size_bytes()
            if size_bytes <= 0:
                raise ingest_error(
                    "MEDIA_EMPTY",
                    "upload contains no bytes",
                    request_id=request_id,
                    retryable=False,
                )
            existing = self._repository.get_video_by_hash(digest)
            if existing is not None:
                return IngestResult(video=existing, reused=True)
            facts = self._probe.probe(staging.local_path())
            validate_probe_facts(
                facts,
                config,
                size_bytes=size_bytes,
                request_id=request_id,
            )
            original = staging.commit(storage_key=content_storage_key(digest))
            committed = True
            return self._persist_new(
                original,
                facts,
                filename=filename,
                digest=digest,
                size_bytes=size_bytes,
            )
        finally:
            if not committed:
                staging.abort()

    def _stream(
        self,
        source: Path,
        staging: StagingObject,
        *,
        max_bytes: int,
        request_id: str,
    ) -> None:
        try:
            handle = source.open("rb")
        except OSError as error:
            raise ingest_error(
                "MEDIA_UNREADABLE",
                "the source file could not be read",
                request_id=request_id,
                retryable=False,
            ) from error
        with handle:
            while True:
                chunk = handle.read(self._chunk_bytes)
                if not chunk:
                    break
                if staging.size_bytes() + len(chunk) > max_bytes:
                    raise ingest_error(
                        "MEDIA_TOO_LARGE",
                        "upload exceeds the configured size limit",
                        request_id=request_id,
                        retryable=False,
                    )
                staging.write(chunk)

    def _persist_new(
        self,
        original: StoredBlob,
        facts: ProbeFacts,
        *,
        filename: str,
        digest: str,
        size_bytes: int,
    ) -> IngestResult:
        probe_digest = sha256(facts.raw_json).hexdigest()
        probe_blob = self._store.put_bytes(
            facts.raw_json,
            storage_key=content_storage_key(probe_digest),
        )
        original_ref = ArtifactRef(
            artifact_id=uuid4(),
            kind="original",
            media_type="application/octet-stream",
            sha256=original.sha256,
            size_bytes=original.size_bytes,
            schema_version=None,
        )
        probe_ref = ArtifactRef(
            artifact_id=uuid4(),
            kind="probe",
            media_type="application/json",
            sha256=probe_blob.sha256,
            size_bytes=probe_blob.size_bytes,
            schema_version=SCHEMA_VERSION,
        )
        metadata = VideoMetadata(
            video_id=uuid4(),
            original_filename=filename,
            content_sha256=digest,
            size_bytes=size_bytes,
            duration_ms=facts.duration_ms,
            width=facts.width,
            height=facts.height,
            display_rotation_degrees=facts.display_rotation_degrees,
            average_frame_rate=facts.average_frame_rate,
            real_frame_rate=facts.real_frame_rate,
            video_codec=facts.video_codec,
            pixel_format=facts.pixel_format,
            has_audio=facts.has_audio,
            audio_codec=facts.audio_codec,
            probe_artifact=probe_ref,
        )
        record = VideoRecord(
            metadata=metadata,
            original_storage_key=original.storage_key,
            probe_storage_key=probe_blob.storage_key,
        )
        self._repository.insert_artifact(original_ref, storage_key=original.storage_key)
        self._repository.insert_artifact(probe_ref, storage_key=probe_blob.storage_key)
        stored = self._repository.insert_video(record)
        reused = stored.metadata.video_id != record.metadata.video_id
        return IngestResult(video=stored, reused=reused)
