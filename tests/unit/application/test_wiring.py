"""Wiring constructs the local Profile A adapters."""

from pathlib import Path

from cine_analyzer.application.wiring import build_services
from cine_analyzer.settings import Settings


def test_build_services_creates_the_local_slice(tmp_path: Path) -> None:
    settings = Settings(artifact_root=tmp_path / "artifacts", state_path=tmp_path / "state.sqlite")
    services = build_services(settings)
    try:
        assert (tmp_path / "artifacts" / "canonical").is_dir()
        assert (tmp_path / "artifacts" / "tmp").is_dir()
        assert services.repository is not None
        assert services.ingest is not None
        assert services.analyze is not None
        assert services.sampling is not None
        assert services.report is not None
    finally:
        services.repository.close()
