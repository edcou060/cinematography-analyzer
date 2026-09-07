"""Structured logging: shape, context isolation, redaction, and total serialization."""

import io
import json
from typing import Any

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from cine_analyzer.logging_setup import (
    REDACTED,
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
)
from cine_analyzer.settings import Settings

_RESERVED_KEYS = frozenset(
    {"event", "level", "timestamp", "service", "logger", "exc_info", "stack_info"},
)


def _configure(stream: io.StringIO, **overrides: str) -> None:
    configure_logging(Settings(**overrides), stream=stream)


def _events(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_an_event_carries_the_documented_field_vocabulary() -> None:
    stream = io.StringIO()
    _configure(stream)

    get_logger("cine_analyzer.tests").info("stage.completed", duration_ms=12)

    event = _events(stream)[0]
    assert event["event"] == "stage.completed"
    assert event["level"] == "info"
    assert event["service"] == "cine-analyzer"
    assert event["logger"] == "cine_analyzer.tests"
    assert event["duration_ms"] == 12
    assert event["timestamp"].endswith("Z")


def test_the_service_field_follows_the_configured_service_name() -> None:
    stream = io.StringIO()
    _configure(stream, service_name="cine-worker-gpu")

    get_logger("t").info("worker.started")

    assert _events(stream)[0]["service"] == "cine-worker-gpu"


def test_events_below_the_configured_level_are_dropped() -> None:
    stream = io.StringIO()
    _configure(stream, log_level="WARNING")
    log = get_logger("t")

    log.debug("noise")
    log.info("also.noise")
    log.warning("kept")

    assert [event["event"] for event in _events(stream)] == ["kept"]


def test_console_format_renders_human_output_rather_than_json() -> None:
    stream = io.StringIO()
    _configure(stream, log_format="console")

    get_logger("t").info("stage.completed")

    rendered = stream.getvalue()
    assert "stage.completed" in rendered
    with pytest.raises(json.JSONDecodeError):
        json.loads(rendered)


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "api_key",
        "X-Api-Key",
        "db_password",
        "signed_url",
        "access_token",
        "credentials",
    ],
)
def test_a_value_whose_key_names_a_credential_never_reaches_the_renderer(key: str) -> None:
    stream = io.StringIO()
    _configure(stream)

    get_logger("t").info("upload.accepted", **{key: "hunter2"})

    event = _events(stream)[0]
    assert event[key] == REDACTED
    assert "hunter2" not in stream.getvalue()


def test_path_keys_and_host_paths_are_redacted() -> None:
    stream = io.StringIO()
    _configure(stream)
    get_logger("t").info(
        "probe.failed",
        path="/Users/me/clip.mp4",
        local_path="/home/me/clip.mp4",
        note="C:\\Users\\me\\clip.mp4",
        hint="/private/tmp/clip.mp4",
        cache="/var/folders/xx/clip.mp4",
        win="D:/tmp/clip.mp4",
        count=3,
        video_id="v-1",
    )
    event = _events(stream)[0]
    assert event["path"] == REDACTED
    assert event["local_path"] == REDACTED
    assert event["note"] == REDACTED
    assert event["hint"] == REDACTED
    assert event["cache"] == REDACTED
    assert event["win"] == REDACTED
    assert event["count"] == 3
    assert event["video_id"] == "v-1"


def test_an_ordinary_key_is_not_redacted() -> None:
    stream = io.StringIO()
    _configure(stream)

    get_logger("t").info("upload.accepted", video_id="v-1")

    assert _events(stream)[0]["video_id"] == "v-1"


def test_bound_context_appears_on_events_and_is_gone_afterwards() -> None:
    stream = io.StringIO()
    _configure(stream)
    log = get_logger("t")

    with bind_context(analysis_id="a-1", stage="shots", attempt=2):
        log.info("stage.started")
    log.info("stage.unrelated")

    inside, outside = _events(stream)
    assert inside["analysis_id"] == "a-1"
    assert inside["stage"] == "shots"
    assert inside["attempt"] == 2
    assert "analysis_id" not in outside


def test_unset_context_fields_are_dropped_rather_than_logged_as_null() -> None:
    stream = io.StringIO()
    _configure(stream)

    with bind_context(request_id="r-1"):
        get_logger("t").info("api.request")

    event = _events(stream)[0]
    assert event["request_id"] == "r-1"
    assert "trace_id" not in event
    assert "worker_id" not in event


def test_nested_context_is_restored_even_when_the_block_raises() -> None:
    stream = io.StringIO()
    _configure(stream)
    log = get_logger("t")

    with bind_context(analysis_id="outer"):
        with pytest.raises(RuntimeError, match="boom"), bind_context(analysis_id="inner"):
            raise RuntimeError("boom")
        log.info("stage.recovered")

    assert _events(stream)[0]["analysis_id"] == "outer"


def test_clearing_context_removes_every_bound_field() -> None:
    stream = io.StringIO()
    _configure(stream)
    log = get_logger("t")

    with bind_context(analysis_id="a-1", video_id="v-1"):
        clear_context()
        log.info("stage.started")

    event = _events(stream)[0]
    assert "analysis_id" not in event
    assert "video_id" not in event


def test_an_object_with_no_json_representation_does_not_break_the_log_call() -> None:
    """A log call is diagnostic code. It must not be the thing that takes a stage down."""

    class Opaque:
        def __repr__(self) -> str:
            return "<Opaque frame buffer>"

    stream = io.StringIO()
    _configure(stream)

    get_logger("t").info("stage.completed", payload=Opaque())

    assert _events(stream)[0]["payload"] == "<Opaque frame buffer>"


def test_an_exception_is_rendered_as_a_string_field() -> None:
    stream = io.StringIO()
    _configure(stream)

    try:
        raise ValueError("probe failed")
    except ValueError:
        get_logger("t").exception("stage.failed", error_code="probe_error")

    event = _events(stream)[0]
    assert event["level"] == "error"
    assert event["error_code"] == "probe_error"
    assert "ValueError: probe failed" in event["exception"]


# Function-scoped fixtures reset structlog between tests, not between Hypothesis
# examples; this test configures its own stream per example, so the health check
# it would otherwise trip does not apply.
@hypothesis_settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=200)
@given(
    payload=st.dictionaries(
        keys=st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True).filter(
            lambda key: key not in _RESERVED_KEYS,
        ),
        values=st.recursive(
            st.none()
            | st.booleans()
            | st.integers()
            | st.floats(allow_nan=False, allow_infinity=False)
            | st.text(),
            lambda children: st.lists(children, max_size=4),
            max_leaves=8,
        ),
        max_size=6,
    ),
)
def test_any_payload_renders_as_exactly_one_parseable_json_line(payload: dict[str, Any]) -> None:
    """Serialization is total, and a value containing newlines cannot forge a second log line."""
    stream = io.StringIO()
    _configure(stream)

    get_logger("t").info("property.probe", **payload)

    rendered = stream.getvalue()
    assert rendered.endswith("\n")
    assert rendered.count("\n") == 1
    assert json.loads(rendered)["event"] == "property.probe"
