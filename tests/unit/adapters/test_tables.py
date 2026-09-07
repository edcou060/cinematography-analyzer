"""SQLAlchemy table modules are import-safe and declare the Phase 08 names."""

from cine_analyzer.adapters.persistence.tables import (
    AnalysisRow,
    ArtifactRow,
    Base,
    CritiqueRunRow,
    ReportSummaryRow,
    ShotRow,
    StageRunRow,
    VideoRow,
    metadata,
)


def test_all_phase_08_tables_are_registered() -> None:
    names = set(metadata.tables)
    assert names == {
        "videos",
        "analyses",
        "artifacts",
        "stage_runs",
        "shots",
        "report_summaries",
        "critique_runs",
    }
    assert Base.metadata is metadata
    assert VideoRow.__tablename__ == "videos"
    assert AnalysisRow.__tablename__ == "analyses"
    assert ArtifactRow.__tablename__ == "artifacts"
    assert StageRunRow.__tablename__ == "stage_runs"
    assert ShotRow.__tablename__ == "shots"
    assert ReportSummaryRow.__tablename__ == "report_summaries"
    assert CritiqueRunRow.__tablename__ == "critique_runs"
