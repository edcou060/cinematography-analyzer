"""Lazy Celery -A entry."""

import pytest


def test_tasks_module_builds_app_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery")
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    from cine_analyzer.worker import tasks

    app = tasks.app
    assert app.conf.task_serializer == "json"
    with pytest.raises(AttributeError, match="no attribute"):
        _ = tasks.not_an_app
