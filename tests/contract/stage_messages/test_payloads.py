"""StageCommand envelopes stay small, JSON, and reference-only."""

import pytest
from tests.factories import make_stage_command, make_stage_result

from cine_analyzer.domain.jobs import QUEUE_PAYLOAD_MAX_BYTES, StageCommand
from cine_analyzer.worker.commands import command_json_bytes, parse_stage_command
from cine_analyzer.worker.queues import QUEUE_CPU_ANALYSIS, QUEUE_GPU_SPATIAL, queue_for_stage


def test_command_and_result_are_under_the_ceiling() -> None:
    command = make_stage_command()
    result = make_stage_result()
    assert len(command_json_bytes(command)) < QUEUE_PAYLOAD_MAX_BYTES
    assert len(result.model_dump_json().encode("utf-8")) < QUEUE_PAYLOAD_MAX_BYTES
    parsed = parse_stage_command(command.model_dump(mode="json"))
    assert parsed.stage_name == command.stage_name


def test_gpu_stage_cannot_use_the_cpu_analysis_queue() -> None:
    assert queue_for_stage("spatial") == QUEUE_GPU_SPATIAL
    assert queue_for_stage("report") == QUEUE_CPU_ANALYSIS
    assert queue_for_stage("spatial") != queue_for_stage("report")


def test_command_rejects_binary_shaped_fields() -> None:
    payload = make_stage_command().model_dump(mode="json")
    payload["ndarray"] = [1, 2, 3]
    with pytest.raises(ValueError, match="ndarray"):
        parse_stage_command(payload)
    StageCommand.model_validate(make_stage_command().model_dump(mode="json"))
