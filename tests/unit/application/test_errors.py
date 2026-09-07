"""Adapter errors become SafeError payloads without paths or stderr."""

from cine_analyzer.application.errors import AdapterError, ingest_error, wrap_adapter


def test_ingest_error_carries_a_safe_payload() -> None:
    error = ingest_error(
        "MEDIA_CORRUPT",
        "the media file could not be probed",
        request_id="r1",
        retryable=False,
    )

    assert error.safe.code == "MEDIA_CORRUPT"
    assert error.safe.request_id == "r1"
    assert "local path" not in error.safe.message
    assert str(error) == error.safe.message


def test_wrap_adapter_infers_probe_stage_from_the_code() -> None:
    wrapped = wrap_adapter(
        AdapterError(
            "PROBE_TIMEOUT", "ffprobe exceeded the configured wall-time limit", retryable=True
        ),
        request_id="r2",
    )

    assert wrapped.safe.stage == "probe"
    assert wrapped.safe.retryable is True


def test_wrap_adapter_defaults_non_probe_codes_to_ingest() -> None:
    wrapped = wrap_adapter(
        AdapterError("ARTIFACT_WRITE", "temporary artifact write failed", retryable=True),
        request_id="r3",
    )

    assert wrapped.safe.stage == "ingest"


def test_wrap_adapter_keeps_an_existing_stage_when_not_overridden() -> None:
    wrapped = wrap_adapter(
        AdapterError("PROBE_FAILED", "ffprobe could not be started", retryable=True, stage="probe"),
        request_id="r5",
    )
    assert wrapped.safe.stage == "probe"
    wrapped = wrap_adapter(
        AdapterError(
            "RESOURCE_STATE", "local state could not be written", retryable=True, stage="ingest"
        ),
        request_id="r4",
        stage="analyze",
    )

    assert wrapped.safe.stage == "analyze"
