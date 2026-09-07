"""CLI fake critic over a fixture report. Does not require a model server."""

import json
from pathlib import Path

from cine_analyzer.cli.main import EXIT_OK, main
from cine_analyzer.domain.types import MetricStatus

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "contract" / "fixtures" / "analysis_report_v1.json"


def test_critique_cli_fake_exits_zero(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(FIXTURE.read_bytes())
    stdout = tmp_path / "out.json"
    import io

    buffer = io.StringIO()
    code = main(["critique", str(report), "--backend", "fake"], stdout=buffer, stderr=io.StringIO())
    assert code == EXIT_OK
    payload = json.loads(buffer.getvalue())
    assert payload["status"] == MetricStatus.OK.value
    assert payload["text"]
    assert "clip.mp4" not in payload["text"]
    stdout.write_text(buffer.getvalue(), encoding="utf-8")


def test_critique_cli_none_omits_prose(tmp_path: Path) -> None:
    import io

    report = tmp_path / "report.json"
    report.write_bytes(FIXTURE.read_bytes())
    buffer = io.StringIO()
    code = main(["critique", str(report), "--backend", "none"], stdout=buffer, stderr=io.StringIO())
    assert code == EXIT_OK
    payload = json.loads(buffer.getvalue())
    assert payload["status"] == MetricStatus.NOT_COMPUTED.value
    assert payload["text"] is None
