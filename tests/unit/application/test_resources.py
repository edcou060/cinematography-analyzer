"""Disk headroom checks never leak paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from cine_analyzer.application.errors import IngestError
from cine_analyzer.application.resources import ensure_disk_headroom


def test_zero_reserve_skips_the_check(tmp_path: Path) -> None:
    ensure_disk_headroom(tmp_path, 0, request_id="r")


def test_enough_free_space_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.application.resources.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=10_000),
    )
    ensure_disk_headroom(tmp_path, 100, request_id="r")


def test_shortfall_and_unreadable_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.application.resources.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=1),
    )
    with pytest.raises(IngestError) as caught:
        ensure_disk_headroom(tmp_path, 100, request_id="r")
    assert caught.value.safe.code == "RESOURCE_DISK"
    assert str(tmp_path) not in caught.value.safe.message

    def _boom(_path: Path) -> object:
        raise OSError("missing")

    monkeypatch.setattr("cine_analyzer.application.resources.shutil.disk_usage", _boom)
    with pytest.raises(IngestError) as unread:
        ensure_disk_headroom(tmp_path, 100, request_id="r")
    assert unread.value.safe.code == "RESOURCE_DISK"
