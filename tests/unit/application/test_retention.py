"""Cleanup only touches tmp/quarantine or a resolved canonical key."""

import os
from pathlib import Path
from time import time

import pytest

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.ingest import content_storage_key
from cine_analyzer.application.retention import delete_canonical_blob, purge_ephemeral


def test_purge_deletes_old_files_and_skips_young_and_symlinks(tmp_path: Path) -> None:
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    old = tmp / "old"
    young = tmp / "young"
    old.write_text("x", encoding="utf-8")
    young.write_text("y", encoding="utf-8")
    os.utime(old, (0, 0))
    (tmp / "nested").mkdir()
    link = tmp / "link"
    link.symlink_to(old)
    deleted = purge_ephemeral(tmp_path, "tmp", max_age_ms=1_000, now_ms=int(time() * 1000))
    assert old.exists() is False
    assert young.exists() is True
    assert deleted >= 1
    assert purge_ephemeral(tmp_path, "quarantine", max_age_ms=0) == 0


def test_forbidden_prefixes_and_canonical_delete(tmp_path: Path) -> None:
    with pytest.raises(AdapterError) as caught:
        purge_ephemeral(tmp_path, "canonical", max_age_ms=0)
    assert caught.value.code == "ARTIFACT_INVALID_KEY"
    with pytest.raises(AdapterError):
        purge_ephemeral(tmp_path, "..", max_age_ms=0)
    with pytest.raises(AdapterError):
        purge_ephemeral(tmp_path, "tmp/nested", max_age_ms=0)
    with pytest.raises(AdapterError):
        purge_ephemeral(tmp_path, "tmp\\nested", max_age_ms=0)
    escaped = tmp_path / "tmp"
    if escaped.exists():
        escaped.rmdir()
    escaped.symlink_to("/")
    with pytest.raises(AdapterError):
        purge_ephemeral(tmp_path, "tmp", max_age_ms=0)
    escaped.unlink()
    store = FilesystemArtifactStore(tmp_path)
    digest = __import__("hashlib").sha256(b"blob").hexdigest()
    key = content_storage_key(digest)
    store.put_bytes(b"blob", storage_key=key)
    delete_canonical_blob(tmp_path, key)
    assert store.contains(key) is False
    delete_canonical_blob(tmp_path, key)
