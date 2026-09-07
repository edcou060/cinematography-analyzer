"""Queue payloads stay small and reference-only (ADR-0004)."""

import pytest
from pydantic import ValidationError
from tests.factories import make_stage_command, make_stage_result

from cine_analyzer.domain.jobs import QUEUE_PAYLOAD_MAX_BYTES, StageCommand, StageResult


def test_stage_command_serializes_under_the_size_budget() -> None:
    encoded = make_stage_command().model_dump_json()

    assert len(encoded.encode("utf-8")) < QUEUE_PAYLOAD_MAX_BYTES
    assert "path" not in encoded
    assert "/Users/" not in encoded


def test_stage_result_serializes_under_the_size_budget() -> None:
    encoded = make_stage_result().model_dump_json()

    assert len(encoded.encode("utf-8")) < QUEUE_PAYLOAD_MAX_BYTES


def test_stage_command_rejects_unknown_fields() -> None:
    payload = make_stage_command().model_dump(mode="json")
    payload["frames"] = []
    with pytest.raises(ValidationError, match="Extra inputs"):
        StageCommand.model_validate(payload)


def test_stage_result_rejects_unknown_fields() -> None:
    payload = make_stage_result().model_dump(mode="json")
    payload["array"] = [1, 2, 3]
    with pytest.raises(ValidationError, match="Extra inputs"):
        StageResult.model_validate(payload)
