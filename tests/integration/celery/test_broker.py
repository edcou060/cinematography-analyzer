"""Real Redis broker smoke. Skips when Redis is not reachable."""

import os

import pytest
from tests.factories import make_stage_command

from cine_analyzer.settings import Settings
from cine_analyzer.worker.celery_app import create_celery_app
from cine_analyzer.worker.queues import TASK_CRITIC, queue_for_stage


def _redis_url() -> str:
    return os.environ.get(
        "PYTEST_REDIS_URL", os.environ.get("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    )


def test_broker_accepts_json_stage_command() -> None:
    pytest.importorskip("redis")
    pytest.importorskip("celery")
    url = _redis_url()
    try:
        import redis

        redis.Redis.from_url(url).ping()
    except Exception as error:
        pytest.skip(f"Redis is not reachable: {error}")
    settings = Settings(execution_backend="celery", redis_url=url)
    app = create_celery_app(settings)
    command = make_stage_command(stage_name="critic")
    result = app.send_task(
        TASK_CRITIC,
        args=[command.model_dump(mode="json")],
        queue=queue_for_stage("critic"),
        serializer="json",
        ignore_result=True,
    )
    assert result.id
    assert "pickle" not in app.conf.accept_content
