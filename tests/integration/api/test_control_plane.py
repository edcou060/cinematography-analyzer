"""API plus local worker against PostgreSQL and the filesystem store."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.adapters.persistence.postgres import PostgresJobRepository
from cine_analyzer.api.app import create_app
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.ingest import IngestVideo
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.settings import Settings
from cine_analyzer.worker.runner import process_once
from cine_analyzer.worker.services import build_worker_services


def test_upload_queue_worker_report_and_reuse(
    pg_repo: PostgresJobRepository,
    tmp_path: Path,
    video_fixtures: Path,
    postgres_url: str,
) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url=postgres_url,
        worker_id="itest-worker",
        lease_ttl_ms=60_000,
    )
    jobs = pg_repo
    store = FilesystemArtifactStore(settings.artifact_root)
    probe = FfprobeMediaProbe(settings.ffprobe_binary, timeout_ms=settings.ffprobe_timeout_ms)
    ingest = IngestVideo(store, probe, jobs, chunk_bytes=settings.ingest_chunk_bytes)
    app = create_app(
        settings=settings,
        jobs=jobs,
        store=store,
        ingest=ingest,
        analyze=CreateAnalysis(jobs),
    )
    clip = video_fixtures / "two_color_cut.mp4"
    with TestClient(app) as client, clip.open("rb") as handle:
        uploaded = client.post(
            "/v1/videos",
            files={"file": ("two_color_cut.mp4", handle, "video/mp4")},
        )
        assert uploaded.status_code == 201
        video_id = uploaded.json()["video_id"]
        created = client.post("/v1/analyses", json={"video_id": video_id})
        assert created.status_code == 202
        analysis_id = created.json()["analysis_id"]
        assert created.json()["reused"] is False
        services = build_worker_services(settings, jobs)
        assert process_once(
            jobs=jobs, services=services, settings=settings, now=datetime.now(tz=UTC)
        )
        status = client.get(f"/v1/analyses/{analysis_id}")
        assert status.status_code == 200
        assert status.json()["state"] in {
            AnalysisState.SUCCEEDED.value,
            AnalysisState.PARTIAL.value,
        }
        report = client.get(f"/v1/analyses/{analysis_id}/report")
        assert report.status_code == 200
        assert report.json()["summary"]["shot_count"] >= 1
        window = client.get(
            f"/v1/analyses/{analysis_id}/timeline",
            params={"start_ms": 0, "end_ms": 10_000, "max_points": 50},
        )
        assert window.status_code in {200, 404}
        reused = client.post("/v1/analyses", json={"video_id": video_id})
        assert reused.status_code == 202
        assert reused.json()["analysis_id"] == analysis_id
        assert reused.json()["reused"] is True
    jobs.close()
