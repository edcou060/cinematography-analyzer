"""Filesystem artifact store: checksum, atomic promote, abort only temps."""

from pathlib import Path

import pytest

from cine_analyzer.adapters.artifacts.filesystem import (
    FilesystemArtifactStore,
    canonical_path,
)
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.ingest import content_storage_key


def test_put_bytes_is_readable_and_content_addressed(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    digest = __import__("hashlib").sha256(b"probe").hexdigest()
    key = content_storage_key(digest)
    blob = store.put_bytes(b"probe", storage_key=key)

    assert blob.sha256 == digest
    assert store.contains(key) is True
    assert b"".join(store.open_read(key)) == b"probe"


def test_commit_is_idempotent_when_the_canonical_checksum_matches(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "aa/" + "a" * 64
    first = store.begin_write()
    first.write(b"same")
    assert first.size_bytes() == 4
    first.commit(storage_key=key)
    second = store.begin_write()
    second.write(b"same")
    blob = second.commit(storage_key=key)

    assert blob.storage_key == key
    assert store.contains(key) is True


def test_a_checksum_mismatch_on_an_existing_key_is_terminal(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "bb/" + "b" * 64
    destination = canonical_path(tmp_path, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"other")
    staging = store.begin_write()
    staging.write(b"data")

    with pytest.raises(AdapterError) as caught:
        staging.commit(storage_key=key)

    assert caught.value.code == "ARTIFACT_CHECKSUM_MISMATCH"
    assert destination.read_bytes() == b"other"


def test_local_path_flushes_small_writes_to_disk(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    staging = store.begin_write()
    payload = b"tiny"
    staging.write(payload)
    path = staging.local_path()
    assert path.stat().st_size == len(payload)
    assert path.read_bytes() == payload
    staging.abort()


def test_local_path_maps_fsync_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FilesystemArtifactStore(tmp_path)
    staging = store.begin_write()
    staging.write(b"x")

    def boom(_fd: int) -> None:
        raise OSError("fsync")

    monkeypatch.setattr("cine_analyzer.adapters.artifacts.filesystem.fsync", boom)
    with pytest.raises(AdapterError) as caught:
        staging.local_path()
    assert caught.value.code == "ARTIFACT_WRITE"
    staging.abort()


def test_abort_deletes_only_the_temporary_object(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "cc/" + "c" * 64
    kept = store.put_bytes(b"keep", storage_key=key)
    staging = store.begin_write()
    staging.write(b"tmp")
    tmp_file = staging.local_path()
    staging.abort()
    assert staging.local_path() == tmp_file
    staging.abort()

    assert not tmp_file.exists()
    assert store.contains(kept.storage_key) is True
    staging_after = store.begin_write()
    staging_after.write(b"ok")
    staging_after.commit(storage_key="dd/" + "d" * 64)
    staging_after.abort()
    assert store.contains("dd/" + "d" * 64) is True


def test_missing_and_invalid_keys_are_rejected(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    with pytest.raises(AdapterError) as missing:
        list(store.open_read("ee/" + "e" * 64))
    assert missing.value.code == "ARTIFACT_MISSING"
    assert store.contains("ee/" + "e" * 64) is False

    for key in ("", "/abs", "AA/x", "x/../y", "x/./y", "x\\y", ".." + "/z", "z" * 300):
        with pytest.raises(AdapterError) as caught:
            canonical_path(tmp_path, key)
        assert caught.value.code == "ARTIFACT_INVALID_KEY"


def test_write_and_commit_on_a_closed_object_fail(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    staging = store.begin_write()
    staging.abort()
    with pytest.raises(AdapterError) as caught:
        staging.write(b"x")
    assert caught.value.code == "ARTIFACT_STAGING_CLOSED"
    with pytest.raises(AdapterError) as caught:
        staging.commit(storage_key="ff/" + "f" * 64)
    assert caught.value.code == "ARTIFACT_STAGING_CLOSED"

    other = store.begin_write()
    other.write(b"once")
    other.commit(storage_key="gg/" + "g" * 64)
    with pytest.raises(AdapterError) as caught:
        other.commit(storage_key="gg/" + "g" * 64)
    assert caught.value.code == "ARTIFACT_STAGING_CLOSED"


def test_put_bytes_aborts_when_commit_cannot_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FilesystemArtifactStore(tmp_path)

    def boom(_self: Path, _target: Path) -> Path:
        raise OSError("no space")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(AdapterError) as caught:
        store.put_bytes(b"x", storage_key="hh/" + "h" * 64)
    assert caught.value.code == "ARTIFACT_PROMOTE"
    assert not any(path.is_file() for path in (tmp_path / "canonical").rglob("*"))


def test_write_maps_os_errors(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    staging = store.begin_write()

    class Boom:
        closed = False

        def write(self, _chunk: bytes) -> int:
            raise OSError("nope")

        def flush(self) -> None:
            raise OSError("nope")

        def fileno(self) -> int:
            return 0

        def close(self) -> None:
            self.closed = True

    original = staging._handle
    original.close()
    staging._handle = Boom()
    with pytest.raises(AdapterError) as caught:
        staging.write(b"x")
    assert caught.value.code == "ARTIFACT_WRITE"


def test_commit_maps_fsync_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = FilesystemArtifactStore(tmp_path)
    staging = store.begin_write()
    staging.write(b"x")

    def boom(_fd: int) -> None:
        raise OSError("fsync")

    monkeypatch.setattr("cine_analyzer.adapters.artifacts.filesystem.fsync", boom)
    with pytest.raises(AdapterError) as caught:
        staging.commit(storage_key="ii/" + "i" * 64)
    assert caught.value.code == "ARTIFACT_WRITE"


def test_open_read_yields_chunked_bytes(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    payload = b"z" * (65_536 + 20)
    key = "jj/" + "j" * 64
    store.put_bytes(payload, storage_key=key)
    chunks = list(store.open_read(key))
    assert b"".join(chunks) == payload
    assert len(chunks) >= 2


def test_a_resolved_key_outside_canonical_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "is_relative_to", lambda _self, _other: False)
    with pytest.raises(AdapterError) as caught:
        canonical_path(tmp_path, "aa/" + "a" * 64)
    assert caught.value.code == "ARTIFACT_INVALID_KEY"


def test_canonical_local_path_is_the_promoted_file(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "kk/" + "k" * 64
    store.put_bytes(b"media", storage_key=key)
    path = store.local_path(key)
    assert path.read_bytes() == b"media"
    with pytest.raises(AdapterError) as missing:
        store.local_path("mm/" + "m" * 64)
    assert missing.value.code == "ARTIFACT_MISSING"


def test_put_replaceable_creates_a_new_key(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "qq/" + "q" * 64
    blob = store.put_replaceable(b"fresh", storage_key=key)
    assert blob.size_bytes == 5
    assert b"".join(store.open_read(key)) == b"fresh"


def test_put_replaceable_overwrites_the_same_key(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "nn/" + "n" * 64
    store.put_bytes(b"first", storage_key=key)
    blob = store.put_replaceable(b"second", storage_key=key)
    assert blob.size_bytes == 6
    assert b"".join(store.open_read(key)) == b"second"


def test_put_replaceable_maps_unlink_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FilesystemArtifactStore(tmp_path)
    key = "pp/" + "p" * 64
    store.put_bytes(b"first", storage_key=key)
    destination = canonical_path(tmp_path, key)
    original = Path.unlink

    def boom(self: Path, *args: object, **kwargs: object) -> None:
        if self.resolve() == destination.resolve():
            raise OSError("busy")
        original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", boom)
    with pytest.raises(AdapterError) as caught:
        store.put_replaceable(b"second", storage_key=key)
    assert caught.value.code == "ARTIFACT_PROMOTE"
