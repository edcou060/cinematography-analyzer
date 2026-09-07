"""Unix child resource limits for media subprocesses.

Wall timeouts and process-group kill remain the primary controls. These rlimits
are best-effort and must never be required for correctness on platforms that
reject them.
"""

import os
from collections.abc import Callable
from typing import TypedDict

__all__ = ["apply_child_limits", "child_preexec", "popen_limit_kwargs"]

_NOFILE = 256
_NPROC = 64
_ADDRESS_SPACE = 4 * 1024 * 1024 * 1024


class _PopenLimits(TypedDict, total=False):
    preexec_fn: Callable[[], None]


def apply_child_limits() -> None:
    """Tighten NOFILE, NPROC, and AS in the child. Swallows unsupported limits."""
    try:
        import resource
    except ImportError:
        return
    _set(resource, "RLIMIT_NOFILE", _NOFILE)
    _set(resource, "RLIMIT_NPROC", _NPROC)
    _set(resource, "RLIMIT_AS", _ADDRESS_SPACE)


def child_preexec() -> Callable[[], None] | None:
    """``Popen(preexec_fn=...)`` value. ``None`` on Windows where it is illegal."""
    if os.name == "nt":
        return None
    return apply_child_limits


def popen_limit_kwargs() -> _PopenLimits:
    """Extra Popen kwargs so Windows never receives ``preexec_fn``."""
    preexec = child_preexec()
    if preexec is None:
        return {}
    return {"preexec_fn": preexec}


def _set(resource_mod: object, name: str, value: int) -> None:
    limit = getattr(resource_mod, name, None)
    setter = getattr(resource_mod, "setrlimit", None)
    if limit is None or setter is None:
        return
    try:
        setter(limit, (value, value))
    except (ValueError, OSError, OverflowError):
        return
