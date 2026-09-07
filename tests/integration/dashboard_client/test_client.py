"""Dashboard HTTP client against the FastAPI control plane (in-process)."""

from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from tests.factories import (
    ANALYSIS_ID,
    DIGEST,
    SHOT_ID,
    VIDEO_ID,
    make_artifact,
    make_availability,
    make_report,
    make_video,
)
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore, video_record_from_bytes
from tests.unit.domain.test_timeline import _point

from cine_analyzer.api.app import create_app
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.ingest import IngestResult
from cine_analyzer.dashboard.client import AnalyzerClient, DashboardClientError
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import SCHEMA_VERSION
from cine_analyzer.ports.control import ReportSummaryRecord, ShotIntervalRecord
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings


class _Ingest:
    def __init__(self, video: VideoRecord, jobs: MemoryJobRepository) -> None:
        self.video = video
        self.jobs = jobs

    def execute(
        self, source: Path, *, original_filename: str, config: object, request_id: str
    ) -> IngestResult:
        del source, original_filename, config, request_id
        stored = self.jobs.insert_video(self.video)
        return IngestResult(video=stored, reused=False)


def _settings(tmp_path: Path) -> Settings:
    return Settings(artifact_root=tmp_path / "artifacts")


def _stack(tmp_path: Path) -> tuple[TestClient, MemoryJobRepository, MemoryStore]:
    repository = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    video = video_record_from_bytes(b"clip")
    app = create_app(
        settings=_settings(tmp_path),
        jobs=repository,
        store=store,
        ingest=_Ingest(video, repository),
        analyze=CreateAnalysis(repository),
    )
    return TestClient(app), repository, store


def _client(http: TestClient) -> AnalyzerClient:
    return AnalyzerClient("http://testserver", client=http)


def test_upload_create_and_status_round_trip(tmp_path: Path) -> None:
    http, jobs, _store = _stack(tmp_path)
    with http:
        client = _client(http)
        assert client.live().status == "ok"
        assert client.ready().status == "ok"
        accepted = client.upload_video(BytesIO(b"clip"), filename="clip.mp4")
        created = client.create_analysis(accepted.video_id)
        status = client.get_status(created.analysis_id)
        canceled = client.cancel(created.analysis_id)
    assert accepted.content_sha256
    assert created.state is AnalysisState.QUEUED
    assert status.state is AnalysisState.QUEUED
    assert canceled.state is AnalysisState.CANCELED
    assert jobs.get_video(accepted.video_id) is not None


def test_report_timeline_shot_and_artifact_bytes(tmp_path: Path) -> None:
    http, jobs, store = _stack(tmp_path)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="1" * 64,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.RUNNING, target=AnalysisState.SUCCEEDED, progress=1.0
    )
    report = make_report(
        availability=make_availability(
            chromatic=StageAvailability.COMPLETE,
            motion=StageAvailability.COMPLETE,
            tension=StageAvailability.COMPLETE,
        )
    )
    report_key = f"analyses/{ANALYSIS_ID.hex}/report.json"
    timeline_key = f"analyses/{ANALYSIS_ID.hex}/timeline.json"
    store.put_bytes(report.model_dump_json().encode("utf-8"), storage_key=report_key)
    timeline = Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(_point(0), _point(500), _point(1000)),
    )
    store.put_bytes(timeline.model_dump_json().encode("utf-8"), storage_key=timeline_key)
    jobs.insert_artifact(make_artifact(kind="analysis_report"), storage_key=report_key)
    timeline_ref = make_artifact(artifact_id=uuid4(), kind="timeline")
    jobs.insert_artifact(timeline_ref, storage_key=timeline_key)
    report_row = jobs.get_artifact_by_storage_key(report_key)
    assert report_row is not None
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=ANALYSIS_ID,
            summary=report.summary,
            availability=report.availability,
            report_artifact_id=report_row.artifact_id,
            timeline_artifact_id=timeline_ref.artifact_id,
        )
    )
    jobs.save_shots(
        ANALYSIS_ID,
        (
            ShotIntervalRecord(
                shot_id=SHOT_ID,
                analysis_id=ANALYSIS_ID,
                shot_index=0,
                start_ms=0,
                end_ms=4000,
            ),
        ),
    )
    original = make_artifact(artifact_id=uuid4(), kind="original", media_type="video/mp4")
    store.put_bytes(b"mp4-bytes", storage_key="orig/key")
    jobs.insert_artifact(original, storage_key="orig/key")

    with http:
        client = _client(http)
        fetched = client.get_report(ANALYSIS_ID)
        window = client.get_timeline(ANALYSIS_ID, start_ms=0, end_ms=1500, max_points=500)
        shot = client.get_shot(ANALYSIS_ID, SHOT_ID)
        payload = client.get_artifact_bytes(original.artifact_id)

    assert fetched.analysis_id == ANALYSIS_ID
    assert window.points
    assert all(0 <= point.at_ms < 1500 for point in window.points)
    assert shot.shot.shot_id == SHOT_ID
    assert payload == b"mp4-bytes"


def test_missing_resources_become_dashboard_errors(tmp_path: Path) -> None:
    http, _jobs, _store = _stack(tmp_path)
    missing = UUID("12345678-1234-4123-8123-123456789012")
    with http:
        client = _client(http)
        with pytest.raises(DashboardClientError) as missing_status:
            client.get_status(uuid4())
        assert missing_status.value.status_code == 404
        assert missing_status.value.safe.code == "ARTIFACT_MISSING"
        with pytest.raises(DashboardClientError) as missing_video:
            client.create_analysis(missing)
        assert missing_video.value.safe.code == "MEDIA_NOT_FOUND"
