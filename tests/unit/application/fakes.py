"""In-memory ports for application tests. No filesystem store or ffprobe."""

from collections.abc import Iterator
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from tests.factories import ANALYSIS_ID, DIGEST, make_video

from cine_analyzer.adapters.media.ffmpeg_audio import FfmpegAudioExtractor
from cine_analyzer.adapters.vision.opencv_motion import OpenCvMotionAnalyzer
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.report import RunReportStages
from cine_analyzer.domain.artifacts import ArtifactRef
from cine_analyzer.domain.config import AnalysisConfig, LimitsConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.time import Rational
from cine_analyzer.ports.ingestion import (
    AnalysisRecord,
    ProbeFacts,
    StoredBlob,
    VideoRecord,
)

REQUEST_ID = "req-phase-03"


def tiny_config(**limit_overrides: int) -> AnalysisConfig:
    """Default analysis config with small, test-friendly limits."""
    payload = {
        "max_upload_bytes": 1_024,
        "max_duration_ms": 10_000,
        "max_width": 4_096,
        "max_height": 2_160,
    }
    payload.update(limit_overrides)
    return AnalysisConfig(limits=LimitsConfig.model_validate(payload))


def make_probe_facts(**overrides: object) -> ProbeFacts:
    facts = ProbeFacts(
        duration_ms=4_000,
        width=320,
        height=240,
        display_rotation_degrees=0,
        average_frame_rate=Rational(numerator=25, denominator=1),
        real_frame_rate=Rational(numerator=25, denominator=1),
        video_codec="h264",
        pixel_format="yuv420p",
        has_audio=False,
        audio_codec=None,
        color_transfer="bt709",
        video_stream_count=1,
        audio_stream_count=0,
        raw_json=b'{"format":{"duration":"4.000000"},"streams":[]}',
    )
    if not overrides:
        return facts
    return replace(facts, **overrides)  # type: ignore[arg-type]


class MemoryStaging:
    """Staging object that writes a local file so a probe can see it."""

    def __init__(self, path: Path, store: "MemoryStore") -> None:
        self._path = path
        self._store = store
        self._buffer = bytearray()
        self._digest = sha256()
        self._committed = False
        self._aborted = False
        path.write_bytes(b"")

    def write(self, chunk: bytes) -> None:
        if self._committed or self._aborted:
            raise AdapterError("ARTIFACT_STAGING_CLOSED", "closed", retryable=False)
        self._buffer.extend(chunk)
        self._digest.update(chunk)
        self._path.write_bytes(bytes(self._buffer))

    def digest(self) -> str:
        return self._digest.hexdigest()

    def size_bytes(self) -> int:
        return len(self._buffer)

    def local_path(self) -> Path:
        return self._path

    def commit(self, *, storage_key: str) -> StoredBlob:
        if self._store.fail_commit:
            raise AdapterError("ARTIFACT_PROMOTE", "commit failed", retryable=True)
        self._committed = True
        data = bytes(self._buffer)
        self._store.blobs[storage_key] = data
        self._path.unlink(missing_ok=True)
        return StoredBlob(sha256=self.digest(), size_bytes=len(data), storage_key=storage_key)

    def abort(self) -> None:
        if self._committed:
            return
        self._aborted = True
        self._path.unlink(missing_ok=True)


class MemoryStore:
    """Dict-backed artifact store."""

    def __init__(self, tmp_dir: Path) -> None:
        self._tmp_dir = tmp_dir
        tmp_dir.mkdir(parents=True, exist_ok=True)
        self.blobs: dict[str, bytes] = {}
        self.fail_commit = False
        self._seq = 0

    def begin_write(self) -> MemoryStaging:
        self._seq += 1
        path = self._tmp_dir / f"stage-{self._seq}"
        return MemoryStaging(path, self)

    def put_bytes(self, data: bytes, *, storage_key: str) -> StoredBlob:
        staging = self.begin_write()
        staging.write(data)
        return staging.commit(storage_key=storage_key)

    def open_read(self, storage_key: str) -> Iterator[bytes]:
        if storage_key not in self.blobs:
            raise AdapterError("ARTIFACT_MISSING", "missing", retryable=False)
        yield self.blobs[storage_key]

    def contains(self, storage_key: str) -> bool:
        return storage_key in self.blobs

    def local_path(self, storage_key: str) -> Path:
        if storage_key not in self.blobs:
            raise AdapterError("ARTIFACT_MISSING", "missing", retryable=False)
        path = self._tmp_dir / storage_key.replace("/", "_")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.blobs[storage_key])
        return path

    def put_replaceable(self, data: bytes, *, storage_key: str) -> StoredBlob:
        self.blobs[storage_key] = data
        digest = sha256(data).hexdigest()
        return StoredBlob(sha256=digest, size_bytes=len(data), storage_key=storage_key)


class FakeProbe:
    """Returns canned facts or raises."""

    def __init__(
        self,
        *,
        facts: ProbeFacts | None = None,
        error: AdapterError | None = None,
    ) -> None:
        self.facts = facts
        self.error = error
        self.seen: list[Path] = []

    def probe(self, path: Path) -> ProbeFacts:
        self.seen.append(path)
        if self.error is not None:
            raise self.error
        if self.facts is None:
            raise AdapterError("PROBE_FAILED", "no facts", retryable=False)
        return self.facts


class FakeRepository:
    """In-memory identity store."""

    def __init__(self) -> None:
        self.videos: dict[str, VideoRecord] = {}
        self.analyses: dict[str, AnalysisRecord] = {}
        self.artifacts: list[tuple[ArtifactRef, str]] = []
        self.replace_video_on_insert: VideoRecord | None = None
        self.replace_analysis_on_insert: AnalysisRecord | None = None
        self.insert_error: AdapterError | None = None

    def get_video_by_hash(self, content_sha256: str) -> VideoRecord | None:
        return self.videos.get(content_sha256)

    def insert_video(self, record: VideoRecord) -> VideoRecord:
        if self.insert_error is not None:
            raise self.insert_error
        existing = self.videos.get(record.metadata.content_sha256)
        if existing is not None:
            return existing
        stored = self.replace_video_on_insert or record
        self.videos[record.metadata.content_sha256] = stored
        return stored

    def get_analysis_by_key(self, analysis_key: str) -> AnalysisRecord | None:
        return self.analyses.get(analysis_key)

    def insert_analysis(self, record: AnalysisRecord) -> AnalysisRecord:
        if self.insert_error is not None:
            raise self.insert_error
        existing = self.analyses.get(record.analysis_key)
        if existing is not None:
            return existing
        stored = self.replace_analysis_on_insert or record
        self.analyses[record.analysis_key] = stored
        return stored

    def insert_artifact(self, ref: ArtifactRef, *, storage_key: str) -> None:
        self.artifacts.append((ref, storage_key))


def video_record_from_bytes(content: bytes, *, filename: str = "clip.mp4") -> VideoRecord:
    """Build a VideoRecord whose hash matches ``content``."""
    digest = sha256(content).hexdigest()
    size = len(content) if content else 1
    metadata = make_video(content_sha256=digest, original_filename=filename, size_bytes=size)
    return VideoRecord(
        metadata=metadata,
        original_storage_key=f"{digest[:2]}/{digest}",
        probe_storage_key="probe/json",
    )


def unique_analysis_record(video: VideoRecord) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key=sha256(b"other-key").hexdigest(),
        state=AnalysisState.QUEUED,
    )


def new_video_id_record(template: VideoRecord) -> VideoRecord:
    metadata = template.metadata.model_copy(update={"video_id": uuid4()})
    return VideoRecord(
        metadata=metadata,
        original_storage_key=template.original_storage_key,
        probe_storage_key=template.probe_storage_key,
    )


def make_run_report_stages(
    sampling: object,
    store: object,
    chromatic: object,
    spatial: object,
    repo: object,
) -> RunReportStages:
    """Report runner with CPU motion and FFmpeg audio adapters."""
    return RunReportStages(
        sampling,  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        chromatic,  # type: ignore[arg-type]
        spatial,  # type: ignore[arg-type]
        OpenCvMotionAnalyzer(),
        FfmpegAudioExtractor("ffmpeg", timeout_ms=30_000, max_stdout_bytes=50_000_000),
        repo,  # type: ignore[arg-type]
    )
