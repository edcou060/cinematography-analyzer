"""Broker ping and GPU worker readiness."""

import sys
from pathlib import Path

import pytest

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.application.readiness import ping_broker
from cine_analyzer.settings import Settings
from cine_analyzer.worker.lifecycle import reset_gpu_detector, worker_is_ready


def test_ping_broker_maps_missing_client_and_failed_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    monkeypatch.delitem(sys.modules, "redis", raising=False)
    real_import = builtins.__import__

    def _import(name: str, *args: object, **kwargs: object) -> object:
        if name == "redis":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    with pytest.raises(AdapterError) as missing:
        ping_broker("redis://127.0.0.1:6379/0")
    assert missing.value.code == "RESOURCE_NOT_READY"

    class _Client:
        def ping(self) -> bool:
            return False

    class _Redis:
        @staticmethod
        def from_url(_url: str, socket_connect_timeout: float) -> _Client:
            del socket_connect_timeout
            return _Client()

    monkeypatch.setattr(builtins, "__import__", real_import)
    fake = type("mod", (), {"Redis": _Redis})
    monkeypatch.setitem(__import__("sys").modules, "redis", fake)
    with pytest.raises(AdapterError) as false_ping:
        ping_broker("redis://127.0.0.1:6379/0")
    assert false_ping.value.code == "RESOURCE_NOT_READY"

    class _Boom:
        @staticmethod
        def from_url(_url: str, _socket_connect_timeout: float) -> object:
            raise OSError("down")

    monkeypatch.setitem(__import__("sys").modules, "redis", type("mod", (), {"Redis": _Boom}))
    with pytest.raises(AdapterError):
        ping_broker("redis://127.0.0.1:6379/0")

    class _OkClient:
        def ping(self) -> bool:
            return True

    class _OkRedis:
        @staticmethod
        def from_url(_url: str, socket_connect_timeout: float) -> _OkClient:
            del socket_connect_timeout
            return _OkClient()

    monkeypatch.setitem(sys.modules, "redis", type("mod", (), {"Redis": _OkRedis}))
    ping_broker("redis://127.0.0.1:6379/0")


def test_worker_is_ready_cpu_and_gpu(tmp_path: Path) -> None:
    reset_gpu_detector()
    ok, detail = worker_is_ready(Settings(artifact_root=tmp_path / "art"), role="cpu")
    assert ok is True
    assert detail == "ok"
    blocked, reason = worker_is_ready(
        Settings(artifact_root=tmp_path / "art", spatial_worker_backend="ultralytics"),
        role="gpu",
    )
    assert blocked is False
    assert "detector" in reason
    file_root = tmp_path / "file-root"
    file_root.write_text("x", encoding="utf-8")
    missing, _detail = worker_is_ready(Settings(artifact_root=file_root), role="cpu")
    assert missing is False
    reset_gpu_detector()
    ready, _ok = worker_is_ready(Settings(artifact_root=tmp_path / "gpu"), role="gpu")
    assert ready is True
    reset_gpu_detector()


def test_worker_ready_when_root_is_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("denied")

    monkeypatch.setattr(Path, "mkdir", _boom)
    ok, detail = worker_is_ready(Settings(artifact_root=tmp_path / "blocked"), role="cpu")
    assert ok is False
    assert "writable" in detail


def test_worker_ready_when_root_is_not_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(artifact_root=tmp_path / "ghost")
    monkeypatch.setattr(Path, "mkdir", lambda *_a, **_k: None)
    monkeypatch.setattr(Path, "is_dir", lambda _self: False)
    ok, detail = worker_is_ready(settings, role="cpu")
    assert ok is False
    assert "directory" in detail
