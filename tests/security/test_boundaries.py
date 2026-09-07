"""Hostile-media and path-safety boundaries."""

import io
import json
from pathlib import Path

import pytest
from tests.unit.application.fakes import FakeProbe, FakeRepository, MemoryStore, tiny_config

from cine_analyzer.adapters.artifacts.filesystem import canonical_path
from cine_analyzer.adapters.media import ffprobe as probe_mod
from cine_analyzer.application.errors import AdapterError, IngestError
from cine_analyzer.application.ingest import IngestVideo
from cine_analyzer.application.retention import purge_ephemeral
from cine_analyzer.logging_setup import REDACTED, configure_logging, get_logger
from cine_analyzer.settings import Settings


def test_canonical_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(AdapterError) as caught:
        canonical_path(tmp_path, "../secret")
    assert caught.value.code == "ARTIFACT_INVALID_KEY"
    with pytest.raises(AdapterError):
        canonical_path(tmp_path, "/etc/passwd")
    assert "passwd" not in caught.value.message


def test_ingest_errors_omit_filename_and_path(tmp_path: Path) -> None:
    source = tmp_path / "secret-name.mp4"
    source.write_bytes(b"")
    ingest = IngestVideo(MemoryStore(tmp_path), FakeProbe(), FakeRepository(), chunk_bytes=8)
    with pytest.raises(IngestError) as caught:
        ingest.execute(
            source,
            original_filename="secret-name.mp4",
            config=tiny_config(),
            request_id="req",
        )
    payload = caught.value.safe.model_dump_json()
    assert "secret-name" not in payload
    assert str(source) not in payload


def test_cleanup_cannot_escape_artifact_root(tmp_path: Path) -> None:
    with pytest.raises(AdapterError):
        purge_ephemeral(tmp_path, "canonical", max_age_ms=0)
    with pytest.raises(AdapterError):
        purge_ephemeral(tmp_path, "/tmp", max_age_ms=0)


def test_logs_redact_paths_filenames_and_stderr() -> None:
    stream = io.StringIO()
    configure_logging(Settings(), stream=stream)
    get_logger("t").info(
        "probe.failed",
        path="/Users/someone/secret.mp4",
        filename="secret.mp4",
        stderr="ffmpeg: /var/folders/xx/error",
        note="/Users/someone/also",
    )
    rendered = stream.getvalue()
    event = json.loads(rendered)
    assert event["path"] == REDACTED
    assert event["filename"] == REDACTED
    assert event["stderr"] == REDACTED
    assert event["note"] == REDACTED
    assert "/Users/someone" not in rendered
    assert "secret.mp4" not in rendered


def test_ffprobe_popen_is_not_a_shell() -> None:
    text = Path(probe_mod.__file__).read_text(encoding="utf-8")
    assert "shell=False" in text
    assert "shell=True" not in text
