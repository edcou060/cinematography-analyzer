"""Child rlimits are best-effort and skipped on Windows."""

import os
from types import SimpleNamespace

import pytest

from cine_analyzer.adapters.media.childproc import (
    apply_child_limits,
    child_preexec,
    popen_limit_kwargs,
)


def test_unix_preexec_is_applied_and_windows_omits_it(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[object] = []

    def _capture(_limit: object, _pair: object) -> None:
        recorded.append((_limit, _pair))

    import resource as resource_mod

    monkeypatch.setattr(resource_mod, "setrlimit", _capture)
    apply_child_limits()
    assert recorded
    monkeypatch.setattr(os, "name", "posix")
    assert child_preexec() is apply_child_limits
    assert "preexec_fn" in popen_limit_kwargs()
    monkeypatch.setattr(os, "name", "nt")
    assert child_preexec() is None
    assert popen_limit_kwargs() == {}


def test_missing_resource_module_and_failed_rlimit(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    import sys

    saved = sys.modules.get("resource")
    monkeypatch.delitem(sys.modules, "resource", raising=False)

    real_import = builtins.__import__

    def _import(name: str, *args: object, **kwargs: object) -> object:
        if name == "resource":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    apply_child_limits()

    monkeypatch.setattr(builtins, "__import__", real_import)
    fake = SimpleNamespace(RLIMIT_NOFILE=1, RLIMIT_NPROC=2, RLIMIT_AS=3, setrlimit=None)
    monkeypatch.setitem(__import__("sys").modules, "resource", fake)
    apply_child_limits()

    def _boom(_limit: object, _pair: object) -> None:
        raise ValueError("unsupported")

    fake.setrlimit = _boom
    apply_child_limits()
    skinny = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "resource", skinny)
    apply_child_limits()
    if saved is not None:
        sys.modules["resource"] = saved
