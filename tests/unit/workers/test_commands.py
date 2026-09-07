"""StageCommand JSON ceiling, extra fields, and host-path rejection."""

from uuid import uuid4

import pytest
from tests.factories import make_stage_command

from cine_analyzer.domain.jobs import QUEUE_PAYLOAD_MAX_BYTES
from cine_analyzer.worker.commands import command_json_bytes, parse_stage_command


def test_factory_command_is_under_the_ceiling() -> None:
    command = make_stage_command()
    encoded = command_json_bytes(command)
    assert len(encoded) < QUEUE_PAYLOAD_MAX_BYTES
    parsed = parse_stage_command(command.model_dump(mode="json"))
    assert parsed.analysis_id == command.analysis_id


def test_payload_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_stage_command(["not", "an", "object"])


def test_forbidden_keys_and_nested_paths_are_rejected() -> None:
    payload = make_stage_command().model_dump(mode="json")
    payload["frames"] = []
    with pytest.raises(ValueError, match="frames"):
        parse_stage_command(payload)

    nested = make_stage_command().model_dump(mode="json")
    nested["trace_id"] = "/Users/someone/clip.mp4"
    with pytest.raises(ValueError, match="filesystem path"):
        parse_stage_command(nested)

    windows = make_stage_command().model_dump(mode="json")
    windows["trace_id"] = "C:\\temp\\clip.mp4"
    with pytest.raises(ValueError, match="filesystem path"):
        parse_stage_command(windows)

    home = make_stage_command().model_dump(mode="json")
    home["trace_id"] = "/home/operator/media"
    with pytest.raises(ValueError, match="filesystem path"):
        parse_stage_command(home)


def test_nested_forbidden_keys_in_lists_are_rejected() -> None:
    payload = make_stage_command().model_dump(mode="json")
    payload["input_artifact_ids"] = [{"path": "/tmp/x"}]
    with pytest.raises(ValueError, match="path"):
        parse_stage_command(payload)


def test_nested_object_forbidden_keys() -> None:
    payload = make_stage_command().model_dump(mode="json")
    payload["trace_id"] = "ok"
    payload["model"] = "weights.bin"
    with pytest.raises(ValueError, match="model"):
        parse_stage_command(payload)
    oversized = make_stage_command().model_dump(mode="json")
    oversized["input_artifact_ids"] = [str(uuid4()) for _ in range(400)]
    with pytest.raises(ValueError, match="ceiling"):
        parse_stage_command(oversized)


def test_nested_object_and_non_string_host_paths_are_walked() -> None:
    nested = make_stage_command().model_dump(mode="json")
    nested["note"] = {"weights": "x"}
    with pytest.raises(ValueError, match="weights"):
        parse_stage_command(nested)
    numbers = make_stage_command().model_dump(mode="json")
    numbers["input_artifact_ids"] = [1]
    with pytest.raises(ValueError):
        parse_stage_command(numbers)


def test_validated_payload_can_still_exceed_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = make_stage_command().model_dump(mode="json")
    monkeypatch.setattr(
        "cine_analyzer.worker.commands.command_json_bytes",
        lambda _command: b"x" * (QUEUE_PAYLOAD_MAX_BYTES + 1),
    )
    with pytest.raises(ValueError, match="ceiling"):
        parse_stage_command(payload)
