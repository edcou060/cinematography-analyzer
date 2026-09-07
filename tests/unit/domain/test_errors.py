"""SafeError taxonomy and retry-class lookup."""

import pytest
from pydantic import ValidationError

from cine_analyzer.domain.errors import ErrorPrefix, RetryClass, SafeError, retry_class_for


def test_every_prefix_has_a_retry_class() -> None:
    expected = {
        ErrorPrefix.MEDIA: RetryClass.TERMINAL,
        ErrorPrefix.PROBE: RetryClass.TRANSIENT,
        ErrorPrefix.SHOT: RetryClass.BOUNDED,
        ErrorPrefix.ARTIFACT: RetryClass.TRANSIENT,
        ErrorPrefix.MODEL: RetryClass.TERMINAL,
        ErrorPrefix.RESOURCE: RetryClass.DEGRADE_OR_RETRY,
        ErrorPrefix.SCHEMA: RetryClass.TERMINAL,
        ErrorPrefix.CANCELED: RetryClass.TERMINAL_CANCELED,
    }

    for prefix, retry_class in expected.items():
        assert retry_class_for(f"{prefix.value}EXAMPLE") is retry_class


def test_an_unknown_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="unrecognised error code prefix"):
        retry_class_for("WEATHER_RAIN")


def test_safe_error_requires_a_known_prefix() -> None:
    with pytest.raises(ValidationError, match="unrecognised error code prefix"):
        SafeError(
            code="WEATHER_RAIN",
            message="it rained",
            retryable=False,
            request_id="req-1",
        )


def test_a_valid_safe_error_round_trips() -> None:
    error = SafeError(
        code="MEDIA_UNSUPPORTED_TRANSFER",
        message="HDR transfer functions are not accepted",
        retryable=False,
        stage="probe",
        request_id="req-1",
        details=({"field": "transfer_characteristics"},),
    )

    assert SafeError.model_validate_json(error.model_dump_json()) == error


def test_unknown_fields_on_safe_error_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        SafeError.model_validate(
            {
                "code": "SCHEMA_INVALID",
                "message": "extra field",
                "retryable": False,
                "request_id": "req-1",
                "traceback": "nope",
            }
        )
