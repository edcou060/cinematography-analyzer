"""Retention helpers. Cleanup never accepts unresolved or canonical prefixes."""

from pathlib import Path
from time import time

from cine_analyzer.adapters.artifacts.filesystem import canonical_path
from cine_analyzer.application.errors import AdapterError

__all__ = ["ALLOWED_CLEANUP_PREFIXES", "delete_canonical_blob", "purge_ephemeral"]

ALLOWED_CLEANUP_PREFIXES = frozenset({"tmp", "quarantine"})


def _invalid_prefix() -> AdapterError:
    return AdapterError(
        "ARTIFACT_INVALID_KEY",
        "cleanup prefix is not an allowed generated prefix",
        retryable=False,
        stage="cleanup",
    )


def purge_ephemeral(
    root: Path,
    prefix: str,
    *,
    max_age_ms: int,
    now_ms: int | None = None,
) -> int:
    """Delete regular files under ``root/prefix`` older than ``max_age_ms``.

    Only ``tmp`` and ``quarantine`` are accepted. Absolute paths, ``..``, and
    extra segments are refused. Symlinks are skipped. Canonical blobs are not
    touched.
    """
    if "/" in prefix or "\\" in prefix or prefix in {".", ".."}:
        raise _invalid_prefix()
    if prefix not in ALLOWED_CLEANUP_PREFIXES:
        raise _invalid_prefix()
    base = root.resolve()
    target = (root / prefix).resolve()
    if not target.is_relative_to(base):
        raise _invalid_prefix()
    if not target.is_dir():
        return 0
    moment = int(time() * 1000) if now_ms is None else now_ms
    deleted = 0
    for path in target.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        age_ms = moment - int(path.stat().st_mtime * 1000)
        if age_ms < max_age_ms:
            continue
        path.unlink()
        deleted += 1
    return deleted


def delete_canonical_blob(root: Path, storage_key: str) -> None:
    """Delete one canonical object after the key has been resolved server-side."""
    path = canonical_path(root, storage_key)
    if path.is_file():
        path.unlink()
