"""Validate StageCommand JSON at the worker boundary (ADR-0004, ADR-0021)."""

import json
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from cine_analyzer.domain.jobs import QUEUE_PAYLOAD_MAX_BYTES, StageCommand
from cine_analyzer.domain.types import SCHEMA_VERSION

__all__ = [
    "FORBIDDEN_COMMAND_KEYS",
    "build_stage_command",
    "command_json_bytes",
    "parse_stage_command",
]

FORBIDDEN_COMMAND_KEYS: Final[frozenset[str]] = frozenset(
    {
        "frames",
        "frame",
        "array",
        "ndarray",
        "model",
        "weights",
        "path",
        "local_path",
        "pickle",
    }
)


def build_stage_command(
    *,
    analysis_id: UUID,
    stage_name: str,
    configuration_hash: str,
    pipeline_version: str,
    trace_id: str,
    input_artifact_ids: tuple[UUID, ...] = (),
    requested_at: datetime | None = None,
) -> StageCommand:
    """Build a reference-only command. Callers must not attach host paths."""
    stamp = datetime.now(tz=UTC) if requested_at is None else requested_at
    return StageCommand(
        schema_version=SCHEMA_VERSION,
        analysis_id=analysis_id,
        stage_name=stage_name,
        input_artifact_ids=input_artifact_ids,
        configuration_hash=configuration_hash,
        pipeline_version=pipeline_version,
        requested_at=stamp,
        trace_id=trace_id,
    )


def command_json_bytes(command: StageCommand) -> bytes:
    """UTF-8 JSON for a validated command."""
    return command.model_dump_json().encode("utf-8")


def parse_stage_command(payload: object) -> StageCommand:
    """Reject oversized, typed-wrong, or host-path payloads before work starts."""
    if not isinstance(payload, dict):
        message = "stage command must be a JSON object"
        raise ValueError(message)
    _reject_forbidden_keys(payload)
    _reject_host_paths(payload)
    encoded = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    if len(encoded) > QUEUE_PAYLOAD_MAX_BYTES:
        message = "stage command exceeds the queue payload ceiling"
        raise ValueError(message)
    command = StageCommand.model_validate(payload)
    dumped = command_json_bytes(command)
    if len(dumped) > QUEUE_PAYLOAD_MAX_BYTES:
        message = "stage command exceeds the queue payload ceiling"
        raise ValueError(message)
    return command


def _reject_forbidden_keys(payload: dict[str, Any], *, _prefix: str = "") -> None:
    for key, value in payload.items():
        if key in FORBIDDEN_COMMAND_KEYS:
            message = f"stage command must not include {key!r}"
            raise ValueError(message)
        if isinstance(value, dict):
            _reject_forbidden_keys(value, _prefix=f"{_prefix}{key}.")
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _reject_forbidden_keys(item, _prefix=f"{_prefix}{key}.")


def _reject_host_paths(value: object) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _reject_host_paths(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_host_paths(item)
        return
    if not isinstance(value, str):
        return
    lowered = value.lower()
    if lowered.startswith(("/users/", "/home/")):
        message = "stage command must not include a host filesystem path"
        raise ValueError(message)
    if len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}:
        message = "stage command must not include a host filesystem path"
        raise ValueError(message)
