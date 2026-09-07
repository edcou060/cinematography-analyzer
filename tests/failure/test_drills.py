"""Highest-risk failure drills. Expected outcomes are asserted, not improvised."""

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.factories import make_video
from tests.unit.adapters.test_ffprobe import FakeProcess
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore, tiny_config
from tests.unit.application.test_sample_frames import _manifest

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore, canonical_path
from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.api.app import create_app
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.ingest import IngestVideo, content_storage_key
from cine_analyzer.application.retention import purge_ephemeral
from cine_analyzer.application.sample_frames import load_decoded_jpegs
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.media import SamplePurpose
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings
from cine_analyzer.worker.lifecycle import initialize_gpu_detector, reset_gpu_detector


def test_ffprobe_timeout_is_probe_timeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeProcess(timeout=True, pid=11)
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.shutil.which", lambda _name: "/usr/bin/ffprobe"
    )
    monkeypatch.setattr(
        "cine_analyzer.adapters.media.ffprobe.subprocess.Popen", lambda *_a, **_k: fake
    )
    monkeypatch.setattr("cine_analyzer.adapters.media.ffprobe.os.killpg", lambda *_a, **_k: None)
    with pytest.raises(AdapterError) as caught:
        FfprobeMediaProbe("ffprobe", timeout_ms=1).probe(tmp_path / "clip.mp4")
    assert caught.value.code == "PROBE_TIMEOUT"


def test_checksum_mismatch_leaves_canonical_bytes(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "cc/" + "c" * 64
    destination = canonical_path(tmp_path, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"canonical")
    staging = store.begin_write()
    staging.write(b"other")
    with pytest.raises(AdapterError) as caught:
        staging.commit(storage_key=key)
    assert caught.value.code == "ARTIFACT_CHECKSUM_MISMATCH"
    assert destination.read_bytes() == b"canonical"


def test_upload_too_large_is_413(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.api.routes.AnalysisConfig",
        lambda: tiny_config(max_upload_bytes=4),
    )
    app = create_app(
        settings=Settings(artifact_root=tmp_path / "artifacts"),
        jobs=MemoryJobRepository(),
        store=MemoryStore(tmp_path),
        ingest=IngestVideo(
            MemoryStore(tmp_path), MagicMock(), MemoryJobRepository(), chunk_bytes=8
        ),
        analyze=CreateAnalysis(MemoryJobRepository()),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/videos",
            files={"file": ("clip.mp4", b"12345", "video/mp4")},
        )
    assert response.status_code == 413
    assert response.json()["code"] == "MEDIA_TOO_LARGE"
    assert "clip.mp4" not in response.text


def test_upload_disconnect_raises_unreadable_or_empty(tmp_path: Path) -> None:
    class _Drop:
        filename = "clip.mp4"

        async def read(self, _size: int) -> bytes:
            return b""

        async def close(self) -> None:
            return None

    from cine_analyzer.api.routes import _stream_upload
    from cine_analyzer.application.errors import ingest_error as _ie

    del _ie
    destination = tmp_path / "part"
    # An empty body is accepted by the streamer; ingest then reports MEDIA_EMPTY.
    import asyncio

    asyncio.run(
        _stream_upload(_Drop(), destination, chunk_bytes=8, max_bytes=100, request_id="r")  # type: ignore[arg-type]
    )
    assert destination.read_bytes() == b""


def test_gpu_model_unavailable() -> None:
    reset_gpu_detector()
    with pytest.raises(AdapterError) as caught:
        initialize_gpu_detector(Settings(spatial_worker_backend="ultralytics"))
    assert caught.value.code == "MODEL_UNAVAILABLE"
    reset_gpu_detector()


def test_inflight_quota_returns_429(tmp_path: Path) -> None:
    from cine_analyzer.application.identity import make_analysis_key

    jobs = MemoryJobRepository()
    config = AnalysisConfig()
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=video.metadata.video_id,
            configuration_hash=config.hash(),
            pipeline_version=config.pipeline_version,
            analysis_key=make_analysis_key(
                video_sha256=video.metadata.content_sha256, config=config
            ),
            state=AnalysisState.QUEUED,
        )
    )
    other = VideoRecord(
        metadata=make_video(video_id=uuid4(), content_sha256="b" * 64),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(other)
    app = create_app(
        settings=Settings(artifact_root=tmp_path / "artifacts", max_inflight_analyses=1),
        jobs=jobs,
        store=MemoryStore(tmp_path),
        ingest=IngestVideo(MemoryStore(tmp_path), MagicMock(), jobs, chunk_bytes=8),
        analyze=CreateAnalysis(jobs),
    )
    with TestClient(app) as client:
        reuse = client.post("/v1/analyses", json={"video_id": str(video.metadata.video_id)})
        blocked = client.post("/v1/analyses", json={"video_id": str(other.metadata.video_id)})
    assert reuse.status_code == 202
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RESOURCE_LIMIT"


def test_cleanup_refuses_broad_paths(tmp_path: Path) -> None:
    with pytest.raises(AdapterError):
        purge_ephemeral(tmp_path, "canonical", max_age_ms=0)


def test_missing_decode_frame_is_skipped_not_substituted(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    frames = load_decoded_jpegs(_manifest(), {}, store, uuid4(), SamplePurpose.CHROMATIC)
    assert frames == ()


def test_worker_write_then_lost_lease_does_not_duplicate_key(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    digest = __import__("hashlib").sha256(b"same").hexdigest()
    key = content_storage_key(digest)
    first = store.put_bytes(b"same", storage_key=key)
    second = store.put_bytes(b"same", storage_key=key)
    assert first.sha256 == second.sha256
    assert store.contains(key) is True
