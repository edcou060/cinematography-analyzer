"""IngestVideo: stream, bound, probe the staging path, persist or reuse."""

from hashlib import sha256
from pathlib import Path

import pytest
from tests.unit.application.fakes import (
    REQUEST_ID,
    FakeProbe,
    FakeRepository,
    MemoryStore,
    make_probe_facts,
    new_video_id_record,
    tiny_config,
    video_record_from_bytes,
)

from cine_analyzer.application.errors import AdapterError, IngestError
from cine_analyzer.application.ingest import IngestVideo, content_storage_key


def _usecase(
    tmp_path: Path,
    *,
    probe: FakeProbe | None = None,
    repo: FakeRepository | None = None,
    store: MemoryStore | None = None,
) -> tuple[IngestVideo, MemoryStore, FakeRepository, FakeProbe]:
    memory = store or MemoryStore(tmp_path)
    repository = repo or FakeRepository()
    media = probe or FakeProbe(facts=make_probe_facts())
    return (
        IngestVideo(memory, media, repository, chunk_bytes=8),
        memory,
        repository,
        media,
    )


def test_content_storage_key_fans_out_by_prefix() -> None:
    digest = "ab" + "c" * 62
    assert content_storage_key(digest) == f"ab/{digest}"


def test_a_new_clip_is_probed_on_the_staging_path_and_persisted(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video-bytes")
    usecase, store, repo, probe = _usecase(tmp_path)

    result = usecase.execute(
        source,
        original_filename=str(source),
        config=tiny_config(),
        request_id=REQUEST_ID,
    )

    assert result.reused is False
    assert result.video.metadata.content_sha256 == sha256(b"video-bytes").hexdigest()
    assert result.video.metadata.original_filename == "clip.mp4"
    assert probe.seen == [tmp_path / "stage-1"]
    assert store.blobs
    assert repo.videos


def test_a_repository_failure_after_promote_is_wrapped(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    repo = FakeRepository()
    repo.insert_error = AdapterError(
        "RESOURCE_STATE", "local state could not be written", retryable=True
    )
    usecase, store, _, _ = _usecase(tmp_path, repo=repo)

    with pytest.raises(IngestError) as caught:
        usecase.execute(
            source,
            original_filename="clip.mp4",
            config=tiny_config(),
            request_id=REQUEST_ID,
        )

    assert caught.value.safe.code == "RESOURCE_STATE"
    assert store.blobs


def test_an_existing_hash_skips_probe_and_leaves_no_blob(tmp_path: Path) -> None:
    content = b"same-bytes"
    source = tmp_path / "clip.mp4"
    source.write_bytes(content)
    repo = FakeRepository()
    repo.videos[sha256(content).hexdigest()] = video_record_from_bytes(content)
    usecase, store, _, probe = _usecase(tmp_path, repo=repo)

    result = usecase.execute(
        source,
        original_filename="clip.mp4",
        config=tiny_config(),
        request_id=REQUEST_ID,
    )

    assert result.reused is True
    assert probe.seen == []
    assert store.blobs == {}


def test_an_insert_collision_is_reported_as_reuse(tmp_path: Path) -> None:
    content = b"race-bytes"
    source = tmp_path / "clip.mp4"
    source.write_bytes(content)
    existing = video_record_from_bytes(content)
    other = new_video_id_record(existing)
    repo = FakeRepository()
    repo.replace_video_on_insert = other
    usecase, _, _, _ = _usecase(tmp_path, repo=repo)

    result = usecase.execute(
        source,
        original_filename="clip.mp4",
        config=tiny_config(),
        request_id=REQUEST_ID,
    )

    assert result.reused is True
    assert result.video.metadata.video_id == other.metadata.video_id


def test_oversized_input_fails_before_probe_and_leaves_no_canonical_blob(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"0123456789")
    usecase, store, _, probe = _usecase(tmp_path)

    with pytest.raises(IngestError) as caught:
        usecase.execute(
            source,
            original_filename="clip.mp4",
            config=tiny_config(max_upload_bytes=8),
            request_id=REQUEST_ID,
        )

    assert caught.value.safe.code == "MEDIA_TOO_LARGE"
    assert probe.seen == []
    assert store.blobs == {}
    assert not (tmp_path / "stage-1").exists()


def test_empty_input_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "empty.mp4"
    source.write_bytes(b"")
    usecase, store, _, _ = _usecase(tmp_path)

    with pytest.raises(IngestError) as caught:
        usecase.execute(
            source,
            original_filename="empty.mp4",
            config=tiny_config(),
            request_id=REQUEST_ID,
        )

    assert caught.value.safe.code == "MEDIA_EMPTY"
    assert store.blobs == {}


def test_unreadable_source_does_not_name_the_path(tmp_path: Path) -> None:
    usecase, _, _, _ = _usecase(tmp_path)
    missing = tmp_path / "missing.mp4"

    with pytest.raises(IngestError) as caught:
        usecase.execute(
            missing,
            original_filename="missing.mp4",
            config=tiny_config(),
            request_id=REQUEST_ID,
        )

    assert caught.value.safe.code == "MEDIA_UNREADABLE"
    assert str(missing) not in caught.value.safe.message


def test_unsupported_probe_facts_abort_staging(tmp_path: Path) -> None:
    source = tmp_path / "hdr.mp4"
    source.write_bytes(b"hdr-bytes")
    usecase, store, _, _ = _usecase(
        tmp_path,
        probe=FakeProbe(facts=make_probe_facts(color_transfer="smpte2084")),
    )

    with pytest.raises(IngestError) as caught:
        usecase.execute(
            source,
            original_filename="hdr.mp4",
            config=tiny_config(),
            request_id=REQUEST_ID,
        )

    assert caught.value.safe.code == "MEDIA_UNSUPPORTED_TRANSFER"
    assert store.blobs == {}


def test_adapter_failures_are_wrapped_with_the_request_id(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    usecase, _, _, _ = _usecase(
        tmp_path,
        probe=FakeProbe(
            error=AdapterError(
                "PROBE_TIMEOUT", "ffprobe exceeded the configured wall-time limit", retryable=True
            )
        ),
    )

    with pytest.raises(IngestError) as caught:
        usecase.execute(
            source,
            original_filename="clip.mp4",
            config=tiny_config(),
            request_id=REQUEST_ID,
        )

    assert caught.value.safe.code == "PROBE_TIMEOUT"
    assert caught.value.safe.request_id == REQUEST_ID
    assert caught.value.safe.stage == "probe"


def test_a_commit_failure_is_wrapped_and_leaves_no_blob(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    store = MemoryStore(tmp_path)
    store.fail_commit = True
    usecase, _, _, _ = _usecase(tmp_path, store=store)

    with pytest.raises(IngestError) as caught:
        usecase.execute(
            source,
            original_filename="clip.mp4",
            config=tiny_config(),
            request_id=REQUEST_ID,
        )

    assert caught.value.safe.code == "ARTIFACT_PROMOTE"
    assert store.blobs == {}
