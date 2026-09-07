"""Start a Celery worker process for CPU or GPU queues."""

from collections.abc import Callable, Sequence
from typing import TextIO

from pydantic import ValidationError

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.logging_setup import configure_logging
from cine_analyzer.settings import load_settings
from cine_analyzer.worker.lifecycle import cap_native_threads, initialize_gpu_detector
from cine_analyzer.worker.queues import queues_for_role

__all__ = ["run_celery_worker"]

EXIT_OK = 0
EXIT_FAILED = 1


def run_celery_worker(
    *,
    role: str,
    queues: str | None,
    stderr: TextIO,
    worker_main: Callable[[Sequence[str]], object] | None = None,
) -> int:
    """Initialize process limits, optionally the GPU detector, then block on Celery."""
    try:
        settings = load_settings()
    except ValidationError as error:
        stderr.write(f"settings are invalid; the Celery worker was not started\n{error}\n")
        return EXIT_FAILED
    if settings.execution_backend != "celery":
        stderr.write("CINE_EXECUTION_BACKEND must be celery to run celery-worker\n")
        return EXIT_FAILED
    if settings.database_url is None:
        stderr.write("CINE_DATABASE_URL is required to run celery-worker\n")
        return EXIT_FAILED
    configure_logging(settings, stream=stderr)
    cap_native_threads(settings.native_thread_cap)
    if role == "gpu":
        try:
            initialize_gpu_detector(settings)
        except AdapterError as error:
            stderr.write(f"{error.code}: {error.message}\n")
            return EXIT_FAILED
    from cine_analyzer.worker.celery_app import create_celery_app

    app = create_celery_app(settings)
    listen = queues_for_role(role) if queues is None else queues
    concurrency = (
        settings.gpu_spatial_concurrency if role == "gpu" else settings.cpu_analysis_concurrency
    )
    pool = "solo" if role == "gpu" else "prefork"
    argv = [
        "worker",
        f"--queues={listen}",
        f"--concurrency={concurrency}",
        f"--pool={pool}",
        "--loglevel=INFO",
    ]
    starter = worker_main if worker_main is not None else app.worker_main
    starter(argv)
    return EXIT_OK
