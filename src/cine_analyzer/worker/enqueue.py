"""Submit StageCommand JSON to Redis. Importing this module does not load Celery."""

from uuid import UUID

from cine_analyzer.domain.jobs import AnalysisState, StageCommand
from cine_analyzer.settings import Settings
from cine_analyzer.worker.commands import build_stage_command, parse_stage_command
from cine_analyzer.worker.queues import queue_for_stage, task_name_for_stage

__all__ = ["enqueue_command", "maybe_enqueue_analysis"]


def maybe_enqueue_analysis(
    analysis_id: UUID,
    *,
    state: AnalysisState,
    reused: bool,
    settings: Settings,
    trace_id: str,
    configuration_hash: str,
    pipeline_version: str,
) -> None:
    """No-op unless the deployment profile is Celery and the row is still queued."""
    if settings.execution_backend != "celery":
        return
    if reused and state is not AnalysisState.QUEUED:
        return
    if state is not AnalysisState.QUEUED:
        return
    command = build_stage_command(
        analysis_id=analysis_id,
        stage_name="orchestrate",
        configuration_hash=configuration_hash,
        pipeline_version=pipeline_version,
        trace_id=trace_id,
    )
    enqueue_command(command, settings=settings)


def enqueue_command(
    command: StageCommand,
    *,
    countdown: float | None = None,
    settings: Settings | None = None,
) -> None:
    """Validate, then publish JSON to the stage's resource queue."""
    parsed = parse_stage_command(command.model_dump(mode="json"))
    from cine_analyzer.settings import load_settings
    from cine_analyzer.worker.celery_app import create_celery_app

    bound = settings if settings is not None else load_settings()
    app = create_celery_app(bound)
    payload = parsed.model_dump(mode="json")
    task_name = task_name_for_stage(parsed.stage_name)
    queue = queue_for_stage(parsed.stage_name)
    if countdown is not None and countdown > 0:
        app.send_task(
            task_name,
            args=[payload],
            queue=queue,
            serializer="json",
            countdown=countdown,
        )
        return
    app.send_task(task_name, args=[payload], queue=queue, serializer="json")
