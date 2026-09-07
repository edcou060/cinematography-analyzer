"""Version 1 fixtures still parse through the current (identity) adapter."""

import json
from pathlib import Path

from cine_analyzer.domain.report import AnalysisReport

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "analysis_report_v1.json"


def adapt_v1(data: dict[str, object]) -> AnalysisReport:
    """Schema 1.0 adapter. Additional versions get their own adapter, not a silent coerce."""
    return AnalysisReport.model_validate(data)


def test_v1_report_fixture_parses() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = adapt_v1(data)

    assert report.schema_version == "1.0"
    assert report.summary.shot_count == 1
