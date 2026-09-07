"""Enqueue is a no-op on the local profile and publishes JSON on Celery."""

from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_stage_command

from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.settings import Settings
from cine_analyzer.worker.enqueue import enqueue_command, maybe_enqueue_analysis
from cine_analyzer.worker.queues import QUEUE_CPU_DECODE, TASK_ORCHESTRATE, TASK_RUN_STAGE


def test_maybe_enqueue_is_noop_unless_celery_queued() -> None:
    calls: list[object] = []

    def fake_enqueue(command: object, **kwargs: object) -> None:
        calls.append(command)
        del kwargs

    import cine_analyzer.worker.enqueue as module

    original = module.enqueue_command
    module.enqueue_command = fake_enqueue  # type: ignore[method-assign]
    try:
        analysis_id = uuid4()
        maybe_enqueue_analysis(
            analysis_id,
            state=AnalysisState.QUEUED,
            reused=False,
            settings=Settings(),
            trace_id="t",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
        )
        assert calls == []
        maybe_enqueue_analysis(
            analysis_id,
            state=AnalysisState.SUCCEEDED,
            reused=True,
            settings=Settings(execution_backend="celery", redis_url="redis://127.0.0.1:6379/0"),
            trace_id="t",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
        )
        assert calls == []
        maybe_enqueue_analysis(
            analysis_id,
            state=AnalysisState.RUNNING,
            reused=False,
            settings=Settings(execution_backend="celery", redis_url="redis://127.0.0.1:6379/0"),
            trace_id="t",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
        )
        assert calls == []
        maybe_enqueue_analysis(
            analysis_id,
            state=AnalysisState.QUEUED,
            reused=True,
            settings=Settings(execution_backend="celery", redis_url="redis://127.0.0.1:6379/0"),
            trace_id="t",
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
        )
        assert len(calls) == 1
    finally:
        module.enqueue_command = original  # type: ignore[method-assign]


def test_enqueue_command_sends_json_to_the_stage_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[object, object, object]] = []

    class _App:
        def send_task(self, name: str, args: object, **kwargs: object) -> None:
            sent.append((name, args, kwargs))

    monkeypatch.setattr(
        "cine_analyzer.worker.celery_app.create_celery_app",
        lambda settings, **kwargs: _App(),
    )
    command = make_stage_command(stage_name="sampling")
    enqueue_command(
        command,
        countdown=1.5,
        settings=Settings(execution_backend="celery", redis_url="redis://127.0.0.1:6379/0"),
    )
    assert sent[0][0] == TASK_RUN_STAGE
    assert sent[0][2]["queue"] == QUEUE_CPU_DECODE
    assert sent[0][2]["serializer"] == "json"
    assert sent[0][2]["countdown"] == 1.5
    orch = make_stage_command(stage_name="orchestrate")
    enqueue_command(
        orch,
        settings=Settings(execution_backend="celery", redis_url="redis://127.0.0.1:6379/0"),
    )
    assert sent[1][0] == TASK_ORCHESTRATE


def test_enqueue_command_loads_process_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")
    sent: list[object] = []

    class _App:
        def send_task(self, name: str, args: object, **kwargs: object) -> None:
            sent.append(name)
            del args, kwargs

    monkeypatch.setattr(
        "cine_analyzer.worker.celery_app.create_celery_app",
        lambda settings, **kwargs: _App(),
    )
    enqueue_command(make_stage_command(stage_name="sampling"))
    assert sent == [TASK_RUN_STAGE]
