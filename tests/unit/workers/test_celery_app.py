"""Celery app is JSON-only and does not treat results as job truth."""

import pytest

from cine_analyzer.settings import Settings
from cine_analyzer.worker.celery_app import attach_tasks, create_celery_app
from cine_analyzer.worker.queues import (
    QUEUE_CPU_DECODE,
    QUEUE_GPU_SPATIAL,
    TASK_CRITIC,
    TASK_GPU_SPATIAL,
    TASK_ORCHESTRATE,
    TASK_RUN_STAGE,
)


def _settings() -> Settings:
    return Settings(execution_backend="celery", redis_url="redis://127.0.0.1:6379/0")


def test_create_requires_a_broker() -> None:
    with pytest.raises(ValueError, match="redis_url"):
        create_celery_app(Settings())


def test_broker_url_override() -> None:
    app = create_celery_app(_settings(), broker_url="redis://override:6379/1")
    assert "override" in str(app.conf.broker_url)


def test_json_only_and_no_result_backend() -> None:
    app = create_celery_app(_settings())
    assert app.conf.task_serializer == "json"
    assert app.conf.accept_content == ["json"]
    assert "pickle" not in app.conf.accept_content
    assert app.conf.task_ignore_result is True
    assert app.conf.result_backend in {None, "disabled://"}
    queues = {item.name for item in app.conf.task_queues}
    assert QUEUE_GPU_SPATIAL in queues
    assert QUEUE_CPU_DECODE in queues
    assert app.conf.task_routes[TASK_GPU_SPATIAL]["queue"] == QUEUE_GPU_SPATIAL
    again = attach_tasks(app)
    assert again is app
    for name in (TASK_ORCHESTRATE, TASK_RUN_STAGE, TASK_GPU_SPATIAL, TASK_CRITIC):
        assert name in app.tasks


def test_attached_tasks_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    monkeypatch.setattr(
        "cine_analyzer.worker.dispatch.execute_orchestrate",
        lambda payload: seen.append("orch"),
    )
    monkeypatch.setattr(
        "cine_analyzer.worker.dispatch.execute_stage_payload",
        lambda payload: seen.append("stage"),
    )
    monkeypatch.setattr(
        "cine_analyzer.worker.dispatch.execute_gpu_spatial_payload",
        lambda payload: seen.append("gpu"),
    )
    monkeypatch.setattr(
        "cine_analyzer.worker.dispatch.execute_critic_payload",
        lambda payload: seen.append("critic"),
    )
    app = create_celery_app(_settings())
    payload = {"ignored": True}
    app.tasks[TASK_ORCHESTRATE].run(payload)
    app.tasks[TASK_RUN_STAGE].run(payload)
    app.tasks[TASK_GPU_SPATIAL].run(payload)
    app.tasks[TASK_CRITIC].run(payload)
    assert seen == ["orch", "stage", "gpu", "critic"]
