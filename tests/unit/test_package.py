"""Import purity.

The exit gate for this phase says package imports trigger no I/O, no model
loading, and no environment mutation. Asserting that from inside the test
process is impossible once the module is already imported, so the check runs in
a fresh interpreter with an audit hook installed, and reports what happened.
"""

import json
import re
import subprocess
import sys
from functools import cache
from typing import Any

import cine_analyzer

# Runs in a subprocess. The audit hook is armed only around the import itself,
# so the interpreter's own start-up file reads are not counted.
_PROBE = """
import json
import os
import sys

observed = []
collecting = False

WATCHED = {
    "socket.connect",
    "subprocess.Popen",
    "os.system",
    "os.putenv",
    "os.unsetenv",
    "os.remove",
    "os.rename",
    "urllib.Request",
}


def audit(event, args):
    if not collecting:
        return
    if event == "open":
        mode = args[1]
        if isinstance(mode, str) and any(flag in mode for flag in "wxa+"):
            observed.append("open:" + mode)
    elif event in WATCHED:
        observed.append(event)


sys.addaudithook(audit)

environment_before = dict(os.environ)
collecting = True
import cine_analyzer
collecting = False
environment_after = dict(os.environ)

import structlog

sys.stdout.write(json.dumps({
    "audit_events": observed,
    "environment_unchanged": environment_before == environment_after,
    "structlog_configured": structlog.is_configured(),
    "eager_submodules": sorted(m for m in sys.modules if m.startswith("cine_analyzer.")),
    "version": cine_analyzer.__version__,
}))
"""


@cache
def _probe() -> dict[str, Any]:
    """Run the probe once and share the report across the assertions below."""
    # Fixed argv, no shell, no user input. -B keeps bytecode writing out of the audit trail.
    completed = subprocess.run(
        [sys.executable, "-B", "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


def test_version_is_a_release_identifier() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", cine_analyzer.__version__)


def test_import_writes_no_files_and_opens_no_sockets() -> None:
    assert _probe()["audit_events"] == []


def test_import_does_not_mutate_the_environment() -> None:
    assert _probe()["environment_unchanged"] is True


def test_import_does_not_configure_logging() -> None:
    assert _probe()["structlog_configured"] is False


def test_import_pulls_in_no_submodule() -> None:
    """Settings, logging, and CLI code must not run merely because someone imported the package."""
    assert _probe()["eager_submodules"] == []


def test_installed_version_matches_the_source_of_truth() -> None:
    assert _probe()["version"] == cine_analyzer.__version__
