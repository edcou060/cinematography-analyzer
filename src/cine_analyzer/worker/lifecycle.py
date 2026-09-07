"""Worker process limits and one-time GPU detector initialization."""

import os
from hashlib import sha256
from typing import Final

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.settings import Settings

__all__ = [
    "FAKE_WEIGHTS_SHA256",
    "THREAD_ENV_NAMES",
    "cap_native_threads",
    "get_gpu_detector",
    "initialize_gpu_detector",
    "reset_gpu_detector",
    "worker_is_ready",
]

FAKE_WEIGHTS_SHA256: Final = sha256(b"cine-analyzer-fake-subject-detector-v1").hexdigest()
"""Declared identity for the fake detector. Not a file digest of licensed weights."""

THREAD_ENV_NAMES: Final[tuple[str, ...]] = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)

_gpu_detector: object | None = None


def reset_gpu_detector() -> None:
    """Drop the process-level detector. Tests only."""
    global _gpu_detector
    _gpu_detector = None


def get_gpu_detector() -> object:
    """Return the detector initialized in this worker process."""
    if _gpu_detector is None:
        message = "the GPU worker process has not initialized a detector"
        raise AdapterError("MODEL_UNAVAILABLE", message, retryable=False, stage="spatial")
    return _gpu_detector


def cap_native_threads(cap: int) -> None:
    """Set native-library thread env vars. Optionally cap OpenCV if it is loaded."""
    value = str(cap)
    for name in THREAD_ENV_NAMES:
        os.environ[name] = value
    try:
        import cv2
    except ImportError:
        return
    setter = getattr(cv2, "setNumThreads", None)
    if setter is not None:
        setter(cap)


def initialize_gpu_detector(settings: Settings) -> object:
    """Load the configured detector once. Wrong weights identity is fatal."""
    global _gpu_detector
    if _gpu_detector is not None:
        return _gpu_detector
    if settings.spatial_worker_backend == "ultralytics":
        message = "the ultralytics extra is not installed"
        raise AdapterError("MODEL_UNAVAILABLE", message, retryable=False, stage="spatial")
    if settings.spatial_worker_backend == "none":
        message = "a GPU worker requires a spatial backend"
        raise AdapterError("MODEL_UNAVAILABLE", message, retryable=False, stage="spatial")
    expected = settings.spatial_weights_sha256
    if expected is not None and expected != FAKE_WEIGHTS_SHA256:
        message = "weights identity is wrong"
        raise AdapterError("MODEL_UNAVAILABLE", message, retryable=False, stage="spatial")
    from cine_analyzer.adapters.vision.fake_subject import FakeSubjectDetector

    _gpu_detector = FakeSubjectDetector()
    return _gpu_detector


def worker_is_ready(settings: Settings, *, role: str) -> tuple[bool, str]:
    """Artifact root exists; GPU role also requires a process-local detector."""
    root = settings.artifact_root
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False, "artifact root is not writable"
    if not root.is_dir():
        return False, "artifact root is not a directory"
    if role != "gpu":
        return True, "ok"
    try:
        initialize_gpu_detector(settings)
        get_gpu_detector()
    except AdapterError:
        return False, "gpu detector is not ready"
    return True, "ok"
