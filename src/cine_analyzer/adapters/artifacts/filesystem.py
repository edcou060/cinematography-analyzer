"""Filesystem artifact store with temporary write, checksum, and atomic promotion."""

from collections.abc import Iterator
from hashlib import sha256
from os import O_RDONLY, fsync
from os import close as os_close
from os import open as os_open
from pathlib import Path
from uuid import uuid4

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.observability.metrics import incr
from cine_analyzer.ports.ingestion import StoredBlob

__all__ = ["FilesystemArtifactStore", "FilesystemStaging"]

_CHUNK_BYTES = 65_536
_KEY_MAX = 255


def _adapter_error(code: str, message: str, *, retryable: bool) -> AdapterError:
    return AdapterError(code, message, retryable=retryable, stage="ingest")


def _fsync_directory(path: Path) -> None:
    descriptor = os_open(path, O_RDONLY)
    try:
        fsync(descriptor)
    finally:
        os_close(descriptor)


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_path(root: Path, storage_key: str) -> Path:
    """Resolve a storage key under ``root/canonical`` without leaving that tree."""
    if not storage_key or len(storage_key) > _KEY_MAX or storage_key.startswith("/"):
        raise _adapter_error(
            "ARTIFACT_INVALID_KEY",
            "artifact key is not a valid storage key",
            retryable=False,
        )
    raw_parts = storage_key.split("/")
    if any(part in {".", "..", ""} for part in raw_parts) or "\\" in storage_key:
        raise _adapter_error(
            "ARTIFACT_INVALID_KEY",
            "artifact key is not a valid storage key",
            retryable=False,
        )
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._/-")
    if any(char not in allowed for char in storage_key):
        raise _adapter_error(
            "ARTIFACT_INVALID_KEY",
            "artifact key is not a valid storage key",
            retryable=False,
        )
    canonical_root = (root / "canonical").resolve()
    destination = (canonical_root / storage_key).resolve()
    if not destination.is_relative_to(canonical_root):
        raise _adapter_error(
            "ARTIFACT_INVALID_KEY",
            "artifact key is not a valid storage key",
            retryable=False,
        )
    return destination


class FilesystemStaging:
    """One temporary object. Abort deletes only this path."""

    def __init__(self, tmp_path: Path, root: Path) -> None:
        self._tmp_path = tmp_path
        self._root = root
        self._digest = sha256()
        self._size = 0
        self._committed = False
        self._aborted = False
        self._handle = tmp_path.open("wb")

    def write(self, chunk: bytes) -> None:
        """Append one chunk and update the running digest."""
        if self._committed or self._aborted or self._handle.closed:
            raise _adapter_error(
                "ARTIFACT_STAGING_CLOSED",
                "cannot write to a closed staging object",
                retryable=False,
            )
        try:
            self._handle.write(chunk)
        except OSError as error:
            raise _adapter_error(
                "ARTIFACT_WRITE",
                "temporary artifact write failed",
                retryable=True,
            ) from error
        self._digest.update(chunk)
        self._size += len(chunk)

    def digest(self) -> str:
        """SHA-256 of bytes written so far."""
        return self._digest.hexdigest()

    def size_bytes(self) -> int:
        """Count of bytes written so far."""
        return self._size

    def local_path(self) -> Path:
        """Absolute path for probing. Never placed in a queue payload or SafeError.

        Bytes are flushed and fsync'd first so another process (ffprobe) can read
        a complete file. Python's stdio buffer is not visible across processes.
        """
        if not self._handle.closed:
            try:
                self._handle.flush()
                fsync(self._handle.fileno())
            except OSError as error:
                raise _adapter_error(
                    "ARTIFACT_WRITE",
                    "temporary artifact write failed",
                    retryable=True,
                ) from error
        return self._tmp_path

    def commit(self, *, storage_key: str) -> StoredBlob:
        """Fsync, checksum, and rename into the canonical key."""
        if self._committed:
            message = "staging object already committed"
            raise _adapter_error("ARTIFACT_STAGING_CLOSED", message, retryable=False)
        if self._aborted or self._handle.closed:
            raise _adapter_error(
                "ARTIFACT_STAGING_CLOSED",
                "cannot commit a closed staging object",
                retryable=False,
            )
        try:
            self._handle.flush()
            fsync(self._handle.fileno())
        except OSError as error:
            self._handle.close()
            raise _adapter_error(
                "ARTIFACT_WRITE",
                "temporary artifact write failed",
                retryable=True,
            ) from error
        self._handle.close()
        destination = canonical_path(self._root, storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = self.digest()
        if destination.exists():
            existing = _digest_file(destination)
            self._tmp_path.unlink(missing_ok=True)
            if existing != digest:
                raise _adapter_error(
                    "ARTIFACT_CHECKSUM_MISMATCH",
                    "canonical artifact already exists with a different checksum",
                    retryable=False,
                )
            self._committed = True
            return StoredBlob(sha256=digest, size_bytes=self._size, storage_key=storage_key)
        try:
            self._tmp_path.replace(destination)
            _fsync_directory(destination.parent)
        except OSError as error:
            raise _adapter_error(
                "ARTIFACT_PROMOTE",
                "atomic artifact promotion failed",
                retryable=True,
            ) from error
        self._committed = True
        return StoredBlob(sha256=digest, size_bytes=self._size, storage_key=storage_key)

    def abort(self) -> None:
        """Delete this temporary object only."""
        if self._committed:
            return
        self._aborted = True
        if not self._handle.closed:
            self._handle.close()
        self._tmp_path.unlink(missing_ok=True)


class FilesystemArtifactStore:
    """Immutable blobs under ``root/canonical``; staging under ``root/tmp``."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._tmp_root = root / "tmp"
        self._canonical_root = root / "canonical"
        self._tmp_root.mkdir(parents=True, exist_ok=True)
        self._canonical_root.mkdir(parents=True, exist_ok=True)

    def begin_write(self) -> FilesystemStaging:
        """Open a unique temporary object under the tmp prefix."""
        tmp_path = self._tmp_root / uuid4().hex
        return FilesystemStaging(tmp_path, self._root)

    def put_bytes(self, data: bytes, *, storage_key: str) -> StoredBlob:
        """Write a small complete blob such as probe JSON."""
        staging = self.begin_write()
        try:
            staging.write(data)
            blob = staging.commit(storage_key=storage_key)
        except AdapterError as error:
            staging.abort()
            operation = "promote" if error.code == "ARTIFACT_PROMOTE" else "write"
            incr("artifact_failures_total", operation=operation)
            raise
        incr("artifact_write_bytes_total", amount=blob.size_bytes, kind="canonical")
        return blob

    def open_read(self, storage_key: str) -> Iterator[bytes]:
        """Yield canonical bytes. Unknown keys fail."""
        path = canonical_path(self._root, storage_key)
        if not path.is_file():
            incr("artifact_failures_total", operation="read")
            raise _adapter_error(
                "ARTIFACT_MISSING",
                "canonical artifact was not found",
                retryable=False,
            )
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk

    def contains(self, storage_key: str) -> bool:
        """True when the canonical key already exists."""
        path = canonical_path(self._root, storage_key)
        return path.is_file()

    def local_path(self, storage_key: str) -> Path:
        """Absolute path of a canonical blob. Never placed in a SafeError."""
        path = canonical_path(self._root, storage_key)
        if not path.is_file():
            incr("artifact_failures_total", operation="read")
            raise _adapter_error(
                "ARTIFACT_MISSING",
                "canonical artifact was not found",
                retryable=False,
            )
        return path

    def put_replaceable(self, data: bytes, *, storage_key: str) -> StoredBlob:
        """Atomically write a stage output that may replace a previous blob at the same key."""
        destination = canonical_path(self._root, storage_key)
        if destination.is_file():
            try:
                destination.unlink()
            except OSError as error:
                incr("artifact_failures_total", operation="promote")
                raise _adapter_error(
                    "ARTIFACT_PROMOTE",
                    "atomic artifact promotion failed",
                    retryable=True,
                ) from error
        return self.put_bytes(data, storage_key=storage_key)
