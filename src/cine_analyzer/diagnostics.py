"""Runtime capability probe.

Answers one question: what can this installation actually do right now? A missing
optional capability is reported as ``unavailable`` with a reason, in the same
vocabulary the analysis report uses for a pillar it could not compute. Nothing
here executes an external binary; it only resolves names on ``PATH``.
"""

import platform
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from cine_analyzer.settings import Settings

__all__ = [
    "SUPPORTED_PYTHON",
    "SUPPORTED_PYTHON_SPECIFIER",
    "Diagnostic",
    "DiagnosticStatus",
    "check_critic",
    "exit_code_for",
    "run_diagnostics",
]

SUPPORTED_PYTHON: Final = (3, 12)
"""Baseline interpreter. Kept in step with ``requires-python`` by a unit test."""

SUPPORTED_PYTHON_SPECIFIER: Final = ">=3.12,<3.13"

# FFmpeg is not a Phase 01 requirement. Ingestion is the first stage that needs
# it, so its absence is a diagnosed capability gap and not an error.
_FFMPEG_FIRST_NEEDED: Final = "first required by Phase 03 ingestion"


class DiagnosticStatus(StrEnum):
    """Outcome of a single capability check."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One capability check and why it landed where it did."""

    name: str
    status: DiagnosticStatus
    detail: str
    required: bool


def check_python_runtime() -> Diagnostic:
    """Confirm the interpreter is the supported baseline."""
    running = sys.version_info[:2]
    implementation = platform.python_implementation()
    version = ".".join(str(part) for part in sys.version_info[:3])
    if running == SUPPORTED_PYTHON:
        return Diagnostic(
            name="python_runtime",
            status=DiagnosticStatus.AVAILABLE,
            detail=f"{implementation} {version} satisfies {SUPPORTED_PYTHON_SPECIFIER}",
            required=True,
        )
    return Diagnostic(
        name="python_runtime",
        status=DiagnosticStatus.FAILED,
        detail=f"{implementation} {version} does not satisfy {SUPPORTED_PYTHON_SPECIFIER}",
        required=True,
    )


def check_settings(settings: "Settings") -> Diagnostic:
    """Report the settings that were successfully validated at startup."""
    return Diagnostic(
        name="settings",
        status=DiagnosticStatus.AVAILABLE,
        detail=(
            f"environment={settings.environment} "
            f"log_level={settings.log_level} "
            f"log_format={settings.log_format}"
        ),
        required=True,
    )


def check_executable(name: str, binary: str, *, first_needed: str) -> Diagnostic:
    """Resolve an optional external executable on ``PATH`` without running it."""
    resolved = shutil.which(binary)
    if resolved is None:
        return Diagnostic(
            name=name,
            status=DiagnosticStatus.UNAVAILABLE,
            detail=f"{binary!r} not found on PATH; {first_needed}",
            required=False,
        )
    return Diagnostic(
        name=name,
        status=DiagnosticStatus.AVAILABLE,
        detail=resolved,
        required=False,
    )


def check_critic(settings: "Settings") -> Diagnostic:
    """Optional interpretation adapter. Missing configuration is unavailable, not fatal."""
    if settings.critic_backend == "none":
        return Diagnostic(
            name="critic",
            status=DiagnosticStatus.UNAVAILABLE,
            detail="backend none; interpretation is optional and disabled",
            required=False,
        )
    if settings.critic_backend == "fake":
        return Diagnostic(
            name="critic",
            status=DiagnosticStatus.AVAILABLE,
            detail="deterministic fake adapter",
            required=False,
        )
    return Diagnostic(
        name="critic",
        status=DiagnosticStatus.AVAILABLE,
        detail=f"openai-compat timeout_ms={settings.critic_timeout_ms}",
        required=False,
    )


def run_diagnostics(settings: "Settings") -> tuple[Diagnostic, ...]:
    """Run every check in a stable order."""
    return (
        check_python_runtime(),
        check_settings(settings),
        check_executable("ffmpeg", settings.ffmpeg_binary, first_needed=_FFMPEG_FIRST_NEEDED),
        check_executable("ffprobe", settings.ffprobe_binary, first_needed=_FFMPEG_FIRST_NEEDED),
        check_critic(settings),
    )


def exit_code_for(diagnostics: tuple[Diagnostic, ...]) -> int:
    """Fail only on a required check.

    An unavailable optional capability is a report, not an error.
    """
    failed = any(
        item.required and item.status is not DiagnosticStatus.AVAILABLE for item in diagnostics
    )
    return 1 if failed else 0
