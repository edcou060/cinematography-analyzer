"""Celery worker process entry."""

import io
from collections.abc import Iterator
from pathlib import Path

import pytest

from cine_analyzer.worker.celery_worker import EXIT_FAILED, EXIT_OK, run_celery_worker
from cine_analyzer.worker.lifecycle import reset_gpu_detector
from cine_analyzer.worker.queues import QUEUE_GPU_SPATIAL, WORKER_CPU_QUEUES


@pytest.fixture(autouse=True)
def _reset_detector() -> Iterator[None]:
    reset_gpu_detector()
    yield
    reset_gpu_detector()


def test_celery_worker_refuses_invalid_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_LOG_LEVEL", "chatty")
    stderr = io.StringIO()
    assert run_celery_worker(role="cpu", queues=None, stderr=stderr) == EXIT_FAILED
    assert "settings are invalid" in stderr.getvalue()


def test_celery_worker_requires_celery_backend_and_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stderr = io.StringIO()
    assert run_celery_worker(role="cpu", queues=None, stderr=stderr) == EXIT_FAILED
    assert "CINE_EXECUTION_BACKEND" in stderr.getvalue()
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    stderr2 = io.StringIO()
    assert run_celery_worker(role="cpu", queues=None, stderr=stderr2) == EXIT_FAILED
    assert "CINE_DATABASE_URL" in stderr2.getvalue()


def test_cpu_and_gpu_worker_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("CINE_DATABASE_URL", "postgresql+pg8000://cine:@127.0.0.1:1/cine")
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path))
    seen: list[list[str]] = []

    def fake_main(argv: list[str]) -> None:
        seen.append(list(argv))

    stderr = io.StringIO()
    code = run_celery_worker(role="cpu", queues=None, stderr=stderr, worker_main=fake_main)
    assert code == EXIT_OK
    assert WORKER_CPU_QUEUES in seen[0][1]
    assert "--pool=prefork" in seen[0]

    reset_gpu_detector()
    code_gpu = run_celery_worker(
        role="gpu", queues=None, stderr=io.StringIO(), worker_main=fake_main
    )
    assert code_gpu == EXIT_OK
    assert QUEUE_GPU_SPATIAL in seen[1][1]
    assert "--pool=solo" in seen[1]

    custom = run_celery_worker(
        role="cpu", queues="ingest", stderr=io.StringIO(), worker_main=fake_main
    )
    assert custom == EXIT_OK
    assert "--queues=ingest" in seen[2]


def test_cpu_worker_uses_app_worker_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("CINE_DATABASE_URL", "postgresql+pg8000://cine:@127.0.0.1:1/cine")
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path))
    seen: list[list[str]] = []

    class _App:
        def worker_main(self, argv: list[str]) -> None:
            seen.append(list(argv))

    monkeypatch.setattr(
        "cine_analyzer.worker.celery_app.create_celery_app",
        lambda _settings: _App(),
    )
    code = run_celery_worker(role="cpu", queues="ingest", stderr=io.StringIO())
    assert code == EXIT_OK
    assert seen[0][1] == "--queues=ingest"


def test_gpu_init_failure_exits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("CINE_DATABASE_URL", "postgresql+pg8000://cine:@127.0.0.1:1/cine")
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("CINE_SPATIAL_WORKER_BACKEND", "ultralytics")
    stderr = io.StringIO()
    code = run_celery_worker(role="gpu", queues=None, stderr=stderr, worker_main=lambda argv: None)
    assert code == EXIT_FAILED
    assert "MODEL_UNAVAILABLE" in stderr.getvalue()
