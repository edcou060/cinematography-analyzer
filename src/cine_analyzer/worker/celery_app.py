"""Celery application: JSON only, no result backend as job truth (ADR-0021)."""

from typing import Any

from cine_analyzer.settings import Settings
from cine_analyzer.worker.queues import (
    QUEUE_CPU_ANALYSIS,
    QUEUE_CPU_DECODE,
    QUEUE_CRITIC,
    QUEUE_GPU_SPATIAL,
    QUEUE_INGEST,
    TASK_CRITIC,
    TASK_GPU_SPATIAL,
    TASK_ORCHESTRATE,
    TASK_RUN_STAGE,
)

__all__ = ["attach_tasks", "create_celery_app"]


def create_celery_app(settings: Settings, *, broker_url: str | None = None) -> Any:
    """Build a Celery app that accepts JSON commands and ignores result values."""
    from celery import Celery
    from kombu import Queue

    broker = broker_url if broker_url is not None else settings.redis_url
    if broker is None:
        message = "redis_url is required to create the Celery app"
        raise ValueError(message)
    app = Celery("cine_analyzer", broker=broker)
    app.conf.update(
        task_ignore_result=True,
        result_backend=None,
        task_serializer="json",
        result_serializer="json",
        event_serializer="json",
        accept_content=["json"],
        result_accept_content=["json"],
        task_default_queue=QUEUE_INGEST,
        task_create_missing_queues=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_acks_on_failure_or_timeout=True,
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        enable_utc=True,
        worker_hijack_root_logger=False,
        task_queues=(
            Queue(QUEUE_INGEST),
            Queue(QUEUE_CPU_DECODE),
            Queue(QUEUE_CPU_ANALYSIS),
            Queue(QUEUE_GPU_SPATIAL),
            Queue(QUEUE_CRITIC),
        ),
        task_routes={
            TASK_ORCHESTRATE: {"queue": QUEUE_INGEST},
            TASK_RUN_STAGE: {"queue": QUEUE_CPU_ANALYSIS},
            TASK_GPU_SPATIAL: {"queue": QUEUE_GPU_SPATIAL},
            TASK_CRITIC: {"queue": QUEUE_CRITIC},
        },
    )
    return attach_tasks(app)


def attach_tasks(app: Any) -> Any:
    """Register thin tasks on ``app``. Bodies lazy-import dispatch so the API can send."""
    if getattr(app, "_cine_tasks_attached", False):
        return app

    @app.task(  # type: ignore[untyped-decorator]
        name=TASK_ORCHESTRATE,
        acks_late=True,
        reject_on_worker_lost=True,
        ignore_result=True,
    )
    def orchestrate_analysis(payload: dict[str, object]) -> None:
        from cine_analyzer.worker.dispatch import execute_orchestrate

        execute_orchestrate(payload)

    @app.task(  # type: ignore[untyped-decorator]
        name=TASK_RUN_STAGE,
        acks_late=True,
        reject_on_worker_lost=True,
        ignore_result=True,
    )
    def run_stage(payload: dict[str, object]) -> None:
        from cine_analyzer.worker.dispatch import execute_stage_payload

        execute_stage_payload(payload)

    @app.task(  # type: ignore[untyped-decorator]
        name=TASK_GPU_SPATIAL,
        acks_late=True,
        reject_on_worker_lost=True,
        ignore_result=True,
    )
    def run_gpu_spatial(payload: dict[str, object]) -> None:
        from cine_analyzer.worker.dispatch import execute_gpu_spatial_payload

        execute_gpu_spatial_payload(payload)

    @app.task(  # type: ignore[untyped-decorator]
        name=TASK_CRITIC,
        acks_late=True,
        reject_on_worker_lost=True,
        ignore_result=True,
    )
    def run_critic(payload: dict[str, object]) -> None:
        from cine_analyzer.worker.dispatch import execute_critic_payload

        execute_critic_payload(payload)

    app._cine_tasks_attached = True
    return app
