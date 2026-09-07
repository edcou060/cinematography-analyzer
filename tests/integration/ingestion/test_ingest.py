"""Local ingest/analyze against generated fixtures."""

import io
import json
import shutil
from pathlib import Path

import pytest
from tests.unit.application.fakes import REQUEST_ID

from cine_analyzer.application.errors import IngestError
from cine_analyzer.application.wiring import Services, build_services
from cine_analyzer.cli.main import EXIT_OK, main
from cine_analyzer.domain.config import AnalysisConfig, LimitsConfig
from cine_analyzer.settings import Settings


def _services(tmp_path: Path) -> Services:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        state_path=tmp_path / "state.sqlite",
        ffprobe_timeout_ms=15_000,
    )
    return build_services(settings)


def test_ingest_and_analyze_reuse_identity(tmp_path: Path, video_fixtures: Path) -> None:
    services = _services(tmp_path)
    source = video_fixtures / "two_color_cut.mp4"
    config = AnalysisConfig()
    try:
        first_video = services.ingest.execute(
            source,
            original_filename="two_color_cut.mp4",
            config=config,
            request_id=REQUEST_ID,
        )
        second_video = services.ingest.execute(
            source,
            original_filename="two_color_cut.mp4",
            config=config,
            request_id=REQUEST_ID,
        )
        first = services.analyze.execute(
            video=first_video.video, config=config, request_id=REQUEST_ID
        )
        second = services.analyze.execute(
            video=second_video.video, config=config, request_id=REQUEST_ID
        )
    finally:
        services.repository.close()

    assert first_video.reused is False
    assert second_video.reused is True
    assert second_video.video.metadata.video_id == first_video.video.metadata.video_id
    assert first.reused is False
    assert second.reused is True
    assert second.analysis.analysis_id == first.analysis.analysis_id


def test_cli_analyze_dry_run_twice_reuses_identity(
    tmp_path: Path,
    video_fixtures: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CINE_STATE_PATH", str(tmp_path / "state.sqlite"))
    source = str(video_fixtures / "two_color_cut.mp4")
    first_out = io.StringIO()
    second_out = io.StringIO()

    assert main(["analyze", source, "--dry-run"], stdout=first_out, stderr=io.StringIO()) == EXIT_OK
    assert (
        main(["analyze", source, "--dry-run"], stdout=second_out, stderr=io.StringIO()) == EXIT_OK
    )

    first = json.loads(first_out.getvalue())
    second = json.loads(second_out.getvalue())
    assert first["analysis_id"] == second["analysis_id"]
    assert second["reused"] is True
    ingest_out = io.StringIO()
    assert main(["ingest", source], stdout=ingest_out, stderr=io.StringIO()) == EXIT_OK
    assert json.loads(ingest_out.getvalue())["reused"] is True


def test_hostile_filenames_ingest_without_a_shell(
    tmp_path: Path,
    video_fixtures: Path,
) -> None:
    services = _services(tmp_path)
    names = ["clip name.mp4", "clip;rm.mp4", "clip_名前.mp4", "-leading.mp4"]
    try:
        for name in names:
            dest = tmp_path / name
            shutil.copyfile(video_fixtures / "two_color_cut.mp4", dest)
            result = services.ingest.execute(
                dest,
                original_filename=name,
                config=AnalysisConfig(),
                request_id=REQUEST_ID,
            )
            assert result.video.metadata.original_filename
            assert "/" not in result.video.metadata.original_filename
    finally:
        services.repository.close()


def test_corrupt_media_is_a_safe_error_without_canonical_orphans(
    tmp_path: Path,
    video_fixtures: Path,
) -> None:
    services = _services(tmp_path)
    try:
        with pytest.raises(IngestError) as caught:
            services.ingest.execute(
                video_fixtures / "corrupt.mp4",
                original_filename="corrupt.mp4",
                config=AnalysisConfig(),
                request_id=REQUEST_ID,
            )
        assert caught.value.safe.code == "MEDIA_CORRUPT"
        assert "corrupt.mp4" not in caught.value.safe.message
        canonical = tmp_path / "artifacts" / "canonical"
        assert not any(path.is_file() for path in canonical.rglob("*"))
    finally:
        services.repository.close()


def test_over_width_fixture_fails_before_analysis(tmp_path: Path, video_fixtures: Path) -> None:
    services = _services(tmp_path)
    config = AnalysisConfig(
        limits=LimitsConfig(
            max_upload_bytes=1_000_000, max_duration_ms=10_000, max_width=320, max_height=240
        )
    )
    try:
        with pytest.raises(IngestError) as caught:
            services.ingest.execute(
                video_fixtures / "over_width.mp4",
                original_filename="over_width.mp4",
                config=config,
                request_id=REQUEST_ID,
            )
        assert caught.value.safe.code == "MEDIA_DIMENSIONS_EXCEEDED"
        canonical = tmp_path / "artifacts" / "canonical"
        assert not any(path.is_file() for path in canonical.rglob("*"))
    finally:
        services.repository.close()


def test_no_audio_clip_is_accepted(tmp_path: Path, video_fixtures: Path) -> None:
    services = _services(tmp_path)
    try:
        result = services.ingest.execute(
            video_fixtures / "no_audio.mp4",
            original_filename="no_audio.mp4",
            config=AnalysisConfig(),
            request_id=REQUEST_ID,
        )
        assert result.video.metadata.has_audio is False
    finally:
        services.repository.close()
