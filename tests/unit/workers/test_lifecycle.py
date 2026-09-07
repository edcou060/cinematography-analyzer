"""GPU detector identity and native thread caps."""

import os
import sys
from collections.abc import Iterator

import pytest

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.settings import Settings
from cine_analyzer.worker.lifecycle import (
    FAKE_WEIGHTS_SHA256,
    THREAD_ENV_NAMES,
    cap_native_threads,
    get_gpu_detector,
    initialize_gpu_detector,
    reset_gpu_detector,
)


@pytest.fixture(autouse=True)
def _reset_detector() -> Iterator[None]:
    reset_gpu_detector()
    yield
    reset_gpu_detector()


def test_cap_native_threads_sets_env_and_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in THREAD_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    cap_native_threads(2)
    assert os.environ["OMP_NUM_THREADS"] == "2"
    cap_native_threads(1)


def test_cap_native_threads_without_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    monkeypatch.delitem(sys.modules, "cv2", raising=False)
    real_import = builtins.__import__

    def _import(name: str, *args: object, **kwargs: object) -> object:
        if name == "cv2":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    cap_native_threads(3)
    assert os.environ["OMP_NUM_THREADS"] == "3"


def test_cap_native_threads_when_opencv_has_no_setter(monkeypatch: pytest.MonkeyPatch) -> None:
    import cv2

    monkeypatch.setattr(cv2, "setNumThreads", None)
    cap_native_threads(4)
    assert os.environ["OMP_NUM_THREADS"] == "4"


def test_gpu_init_is_once_and_get_requires_init() -> None:
    with pytest.raises(AdapterError, match="has not initialized"):
        get_gpu_detector()
    settings = Settings()
    first = initialize_gpu_detector(settings)
    second = initialize_gpu_detector(settings)
    assert first is second
    assert get_gpu_detector() is first


def test_gpu_readiness_failures() -> None:
    with pytest.raises(AdapterError, match="ultralytics"):
        initialize_gpu_detector(Settings(spatial_worker_backend="ultralytics"))
    reset_gpu_detector()
    with pytest.raises(AdapterError, match="spatial backend"):
        initialize_gpu_detector(Settings(spatial_worker_backend="none"))
    reset_gpu_detector()
    with pytest.raises(AdapterError, match="weights identity"):
        initialize_gpu_detector(Settings(spatial_weights_sha256="0" * 64))
    reset_gpu_detector()
    detector = initialize_gpu_detector(Settings(spatial_weights_sha256=FAKE_WEIGHTS_SHA256))
    assert detector is not None
