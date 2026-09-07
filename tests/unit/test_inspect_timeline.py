"""inspect-timeline prints tension-proxy peaks without filesystem paths."""

import io
import json
from hashlib import sha256
from pathlib import Path

import pytest
from tests.factories import ANALYSIS_ID, DIGEST, make_artifact, make_report

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.application.ingest import content_storage_key
from cine_analyzer.cli.main import EXIT_FAILED, EXIT_OK, main
from cine_analyzer.domain.temporal import TensionComponents
from cine_analyzer.domain.timeline import Timeline, TimelinePoint
from cine_analyzer.domain.types import SCHEMA_VERSION


def _timeline() -> Timeline:
    return Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(
            TimelinePoint(
                at_ms=0,
                shot_index=0,
                tension=TensionComponents(
                    cut_activity=0.1,
                    audio_activity=0.0,
                    motion_activity=0.2,
                    combined_proxy=0.15,
                ),
            ),
            TimelinePoint(
                at_ms=500,
                shot_index=0,
                tension=TensionComponents(
                    cut_activity=0.9,
                    audio_activity=0.0,
                    motion_activity=0.2,
                    combined_proxy=0.6,
                ),
            ),
        ),
    )


def test_inspect_timeline_prints_tension_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(artifact_root))
    store = FilesystemArtifactStore(artifact_root)
    payload = _timeline().model_dump_json().encode("utf-8")
    digest = sha256(payload).hexdigest()
    store.put_bytes(payload, storage_key=content_storage_key(digest))
    report = make_report(
        timeline_artifact=make_artifact(kind="timeline", sha256=digest, size_bytes=len(payload))
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    stdout = io.StringIO()
    code = main(["inspect-timeline", str(path)], stdout=stdout, stderr=io.StringIO())
    assert code == EXIT_OK
    body = stdout.getvalue()
    data = json.loads(body)
    assert data["label"] == "tension proxy"
    assert data["point_count"] == 2
    assert data["peaks"][0]["cut_activity"] == 0.9
    assert "emotion" not in body.lower()
    assert str(tmp_path) not in body


def test_inspect_timeline_rejects_a_missing_file(tmp_path: Path) -> None:
    stderr = io.StringIO()
    code = main(
        ["inspect-timeline", str(tmp_path / "missing.json")],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_FAILED
    payload = json.loads(stderr.getvalue().splitlines()[-1])
    assert payload["code"] == "SCHEMA_INVALID"
    assert "missing.json" not in payload["message"]


def test_inspect_timeline_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("{}", encoding="utf-8")
    stderr = io.StringIO()
    code = main(["inspect-timeline", str(path)], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert json.loads(stderr.getvalue().splitlines()[-1])["code"] == "SCHEMA_INVALID"


def test_inspect_timeline_requires_a_timeline_artifact(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(make_report().model_dump_json(), encoding="utf-8")
    stderr = io.StringIO()
    code = main(["inspect-timeline", str(path)], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert json.loads(stderr.getvalue().splitlines()[-1])["code"] == "ARTIFACT_MISSING"


def test_inspect_timeline_missing_blob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    report = make_report(timeline_artifact=make_artifact(kind="timeline", sha256=DIGEST))
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    stderr = io.StringIO()
    code = main(["inspect-timeline", str(path)], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    message = json.loads(stderr.getvalue().splitlines()[-1])["message"]
    assert "not available" in message
    assert str(tmp_path) not in message


def test_inspect_timeline_rejects_an_invalid_timeline_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(artifact_root))
    store = FilesystemArtifactStore(artifact_root)
    payload = b"{}"
    digest = sha256(payload).hexdigest()
    store.put_bytes(payload, storage_key=content_storage_key(digest))
    report = make_report(
        timeline_artifact=make_artifact(kind="timeline", sha256=digest, size_bytes=2)
    )
    path = tmp_path / "report.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    stderr = io.StringIO()
    code = main(["inspect-timeline", str(path)], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert json.loads(stderr.getvalue().splitlines()[-1])["code"] == "SCHEMA_INVALID"


def test_inspect_timeline_reports_invalid_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CINE_LOG_LEVEL", "nope")
    path = tmp_path / "report.json"
    path.write_text(make_report().model_dump_json(), encoding="utf-8")
    stderr = io.StringIO()
    code = main(["inspect-timeline", str(path)], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert "settings are invalid" in stderr.getvalue()
