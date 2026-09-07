"""Published sample report is a real fixture analysis, not a host dump."""

from pathlib import Path

from cine_analyzer.domain.config import AnalysisConfig, canonical_hash
from cine_analyzer.domain.report import AnalysisReport, StageAvailability

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "examples" / "sample-report.json"


def test_sample_report_validates_without_host_paths() -> None:
    text = SAMPLE.read_text(encoding="utf-8")
    assert "/Users/" not in text
    assert "/tmp/" not in text
    assert "edgarcoutinoocampo" not in text
    report = AnalysisReport.model_validate_json(text)
    assert report.schema_version == "1.0"
    assert report.pipeline_version == "0.1.0"
    assert report.configuration_hash == canonical_hash(AnalysisConfig())
    assert report.video.original_filename == "two_color_cut.mp4"
    assert report.video.has_audio is False
    assert report.availability.shots is StageAvailability.COMPLETE
    assert report.availability.chromatic is StageAvailability.COMPLETE
    assert report.availability.spatial is StageAvailability.UNAVAILABLE
    assert report.availability.audio is StageAvailability.UNAVAILABLE
    assert report.shots[0].spatial.reason_code == "detector_not_installed"
    assert report.critique is None
