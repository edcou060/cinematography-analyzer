"""Capability probing behind ``doctor``."""

import sys

import pytest

from cine_analyzer.diagnostics import (
    Diagnostic,
    DiagnosticStatus,
    check_critic,
    check_executable,
    check_python_runtime,
    exit_code_for,
    run_diagnostics,
)
from cine_analyzer.settings import Settings, load_settings


def test_the_running_interpreter_is_the_supported_baseline() -> None:
    check = check_python_runtime()

    assert check.status is DiagnosticStatus.AVAILABLE
    assert check.required is True


def test_an_unsupported_interpreter_fails_the_required_runtime_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 11, 9, "final", 0))

    check = check_python_runtime()

    assert check.status is DiagnosticStatus.FAILED
    assert "3.11.9" in check.detail
    assert ">=3.12,<3.13" in check.detail
    assert exit_code_for((check,)) == 1


def test_diagnostics_run_in_a_stable_order() -> None:
    names = [check.name for check in run_diagnostics(load_settings())]

    assert names == ["python_runtime", "settings", "ffmpeg", "ffprobe", "critic"]


def test_a_resolved_executable_reports_where_it_was_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _binary: "/usr/local/bin/ffmpeg")

    check = check_executable("ffmpeg", "ffmpeg", first_needed="Phase 03")

    assert check.status is DiagnosticStatus.AVAILABLE
    assert check.detail == "/usr/local/bin/ffmpeg"


def test_a_missing_executable_is_unavailable_with_a_reason_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FFmpeg is not a Phase 01 requirement, so its absence is diagnosed, not fatal."""
    monkeypatch.setattr("shutil.which", lambda _binary: None)

    check = check_executable("ffmpeg", "ffmpeg", first_needed="required by Phase 03")

    assert check.status is DiagnosticStatus.UNAVAILABLE
    assert check.required is False
    assert "required by Phase 03" in check.detail
    assert exit_code_for((check,)) == 0


def test_settings_check_reports_the_validated_values() -> None:
    check = run_diagnostics(load_settings())[1]

    assert check.status is DiagnosticStatus.AVAILABLE
    assert "environment=local" in check.detail
    assert "log_level=INFO" in check.detail


def test_a_failed_required_check_produces_a_nonzero_exit_code() -> None:
    failure = Diagnostic(
        name="python_runtime",
        status=DiagnosticStatus.FAILED,
        detail="CPython 3.11.9 does not satisfy >=3.12,<3.13",
        required=True,
    )

    assert exit_code_for((failure,)) == 1


def test_an_empty_diagnostic_set_is_not_treated_as_a_failure() -> None:
    assert exit_code_for(()) == 0


def test_critic_diagnostic_is_optional() -> None:
    none = check_critic(Settings())
    assert none.status is DiagnosticStatus.UNAVAILABLE
    assert none.required is False
    fake = check_critic(Settings(critic_backend="fake"))
    assert fake.status is DiagnosticStatus.AVAILABLE
    openai = check_critic(
        Settings(critic_backend="openai", critic_base_url="http://127.0.0.1:11434")
    )
    assert openai.status is DiagnosticStatus.AVAILABLE
    assert "timeout_ms=" in openai.detail
