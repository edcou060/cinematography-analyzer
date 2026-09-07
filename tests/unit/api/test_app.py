"""Thin API: SafeError, 202, status, cancel, bounded artifacts. No CV imports."""

import json
from datetime import UTC, datetime
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
from tests.unit.application.fakes import MemoryStore, tiny_config, video_record_from_bytes
from tests.unit.domain.test_timeline import _point

from cine_analyzer.api.app import create_app
from cine_analyzer.api.deps import request_id_of, settings_of
from cine_analyzer.api.errors import ApiError
from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.errors import AdapterError, ingest_error
from cine_analyzer.application.ingest import IngestResult
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import Critique, StageAvailability
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.domain.types import SCHEMA_VERSION, MetricStatus
from cine_analyzer.ports.control import CritiqueRunRecord, ReportSummaryRecord, ShotIntervalRecord
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings


class _Ingest:
    def __init__(self, video: VideoRecord, *, error: Exception | None = None) -> None:
        self.video = video
        self.error = error
        self.seen: list[Path] = []

    def execute(
        self, source: Path, *, original_filename: str, config: object, request_id: str
    ) -> IngestResult:
        del original_filename, config, request_id
        self.seen.append(source)
        if self.error is not None:
            raise self.error
        return IngestResult(video=self.video, reused=False)


def _settings(tmp_path: Path) -> Settings:
    return Settings(artifact_root=tmp_path / "artifacts")


def _client(
    tmp_path: Path,
    *,
    jobs: MemoryJobRepository | None = None,
    ingest: object | None = None,
) -> tuple[TestClient, MemoryJobRepository, MemoryStore]:
    repository = MemoryJobRepository() if jobs is None else jobs
    store = MemoryStore(tmp_path)
    video = video_record_from_bytes(b"clip")
    app = create_app(
        settings=_settings(tmp_path),
        jobs=repository,
        store=store,
        ingest=_Ingest(video) if ingest is None else ingest,  # type: ignore[arg-type]
        analyze=CreateAnalysis(repository),
    )
    return TestClient(app), repository, store


def test_metrics_without_a_repository(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.json()["gauges"][0]["name"] == "analysis_active_jobs"


def test_live_does_not_need_a_database(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_is_unavailable_without_a_repository(tmp_path: Path) -> None:
    app = create_app(settings=_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_ready_pings_broker_when_celery_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def _ping(url: str) -> None:
        seen.append(url)

    monkeypatch.setattr("cine_analyzer.api.routes.ping_broker", _ping)
    jobs = MemoryJobRepository()
    app = create_app(
        settings=Settings(
            artifact_root=tmp_path / "artifacts",
            execution_backend="celery",
            redis_url="redis://127.0.0.1:6379/0",
        ),
        jobs=jobs,
        store=MemoryStore(tmp_path),
        ingest=_Ingest(video_record_from_bytes(b"clip")),
        analyze=CreateAnalysis(jobs),
    )
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert seen == ["redis://127.0.0.1:6379/0"]

    def _fail(_url: str) -> None:
        raise AdapterError("RESOURCE_NOT_READY", "broker down", retryable=True, stage="control")

    monkeypatch.setattr("cine_analyzer.api.routes.ping_broker", _fail)
    with TestClient(app) as client:
        blocked = client.get("/health/ready")
    assert blocked.status_code == 503


def test_metrics_swallows_inflight_count_errors(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    jobs.fail_reads = True
    client, _jobs, _store = _client(tmp_path, jobs=jobs)
    with client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert response.json()["gauges"][0]["value"] == 0


def test_ready_ok_and_echoes_request_id(tmp_path: Path) -> None:
    client, _jobs, _store = _client(tmp_path)
    with client:
        response = client.get("/health/ready", headers={"X-Request-ID": "trace-abc"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-abc"


def test_ready_maps_ingest_error_without_leaking_stage_none(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()

    def boom() -> None:
        raise AdapterError("RESOURCE_STATE", "unreachable", retryable=True)

    jobs.ping = boom  # type: ignore[method-assign]
    client, _jobs, _store = _client(tmp_path, jobs=jobs)
    with client:
        response = client.get("/health/ready")
    assert response.status_code == 503

    def ingest_boom() -> None:
        raise ingest_error("RESOURCE_STATE", "db", request_id="req", retryable=True)

    jobs.ping = ingest_boom  # type: ignore[method-assign]
    with client:
        ingest_failed = client.get("/health/ready")
    assert ingest_failed.status_code == 503


def test_upload_streams_chunks(tmp_path: Path) -> None:
    video = video_record_from_bytes(b"clip")
    ingest = _Ingest(video)
    client, _jobs, _store = _client(tmp_path, ingest=ingest)
    with client:
        response = client.post(
            "/v1/videos",
            files={"file": ("clip.mp4", b"not-empty", "video/mp4")},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["reused"] is False
    assert body["content_sha256"] == video.metadata.content_sha256
    assert ingest.seen


def test_analysis_create_returns_202_and_reuses(tmp_path: Path) -> None:
    client, jobs, _store = _client(tmp_path)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    with client:
        first = client.post("/v1/analyses", json={"video_id": str(VIDEO_ID)})
        second = client.post("/v1/analyses", json={"video_id": str(VIDEO_ID)})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["analysis_id"] == second.json()["analysis_id"]
    assert second.json()["reused"] is True
    assert jobs.list_stage_runs(UUID(first.json()["analysis_id"]))


def test_create_analysis_enqueues_on_celery_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def _capture(*args: object, **kwargs: object) -> None:
        seen.append(kwargs.get("state"))

    monkeypatch.setattr("cine_analyzer.api.routes.maybe_enqueue_analysis", _capture)
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    app = create_app(
        settings=Settings(
            artifact_root=tmp_path / "artifacts",
            execution_backend="celery",
            redis_url="redis://127.0.0.1:6379/0",
        ),
        jobs=jobs,
        store=store,
        ingest=_Ingest(video),
        analyze=CreateAnalysis(jobs),
    )
    with TestClient(app) as client:
        response = client.post("/v1/analyses", json={"video_id": str(VIDEO_ID)})
    assert response.status_code == 202
    assert seen


def test_unknown_video_is_media_not_found(tmp_path: Path) -> None:
    client, _jobs, _store = _client(tmp_path)
    with client:
        response = client.post("/v1/analyses", json={"video_id": str(uuid4())})
    assert response.status_code == 404
    assert response.json()["code"] == "MEDIA_NOT_FOUND"


def test_invalid_body_is_schema_invalid(tmp_path: Path) -> None:
    client, _jobs, _store = _client(tmp_path)
    with client:
        response = client.post("/v1/analyses", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "SCHEMA_INVALID"


def test_missing_analysis_is_artifact_missing(tmp_path: Path) -> None:
    client, _jobs, _store = _client(tmp_path)
    with client:
        response = client.get(f"/v1/analyses/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "ARTIFACT_MISSING"


def test_status_and_cancel_and_report_not_ready(tmp_path: Path) -> None:
    client, jobs, _store = _client(tmp_path)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    analysis = jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="f" * 64,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.ensure_pending_stages(analysis.analysis_id)
    with client:
        status = client.get(f"/v1/analyses/{ANALYSIS_ID}")
        report = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
        timeline = client.get(
            f"/v1/analyses/{ANALYSIS_ID}/timeline",
            params={"start_ms": 0, "end_ms": 10, "max_points": 2},
        )
        cancel = client.post(f"/v1/analyses/{ANALYSIS_ID}/cancel")
        missing_cancel = client.post(f"/v1/analyses/{uuid4()}/cancel")
    assert status.status_code == 200
    assert status.json()["state"] == "QUEUED"
    assert report.status_code == 409
    assert report.json()["code"] == "RESOURCE_NOT_READY"
    assert timeline.status_code == 409
    assert cancel.status_code == 200
    assert cancel.json()["state"] == "CANCELED"
    assert missing_cancel.status_code == 404


def test_critique_is_separate_from_the_report(tmp_path: Path) -> None:
    client, jobs, store = _client(tmp_path)
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
            analysis_key="c" * 64,
            state=AnalysisState.SUCCEEDED,
        )
    )
    report = make_report()
    key = f"analyses/{ANALYSIS_ID.hex}/report.json"
    store.put_bytes(report.model_dump_json().encode("utf-8"), storage_key=key)
    artifact = make_artifact(kind="analysis_report")
    jobs.insert_artifact(artifact, storage_key=key)
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=ANALYSIS_ID,
            summary=report.summary,
            availability=make_availability(),
            report_artifact_id=artifact.artifact_id,
            timeline_artifact_id=None,
        )
    )
    with client:
        missing = client.get(f"/v1/analyses/{uuid4()}/critique")
        empty = client.get(f"/v1/analyses/{ANALYSIS_ID}/critique")
        fetched = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
    assert missing.status_code == 404
    assert empty.status_code == 200
    assert empty.json()["status"] == "NOT_COMPUTED"
    assert fetched.status_code == 200
    assert fetched.json()["critique"] is None
    jobs.save_critique(
        CritiqueRunRecord(
            critique_run_id=uuid4(),
            analysis_id=ANALYSIS_ID,
            critique=Critique(
                status=MetricStatus.OK,
                text="The clip has 1 detected shots with mean length 4.0 s and median 4.0 s.",
                model_name="fake:deterministic-v1",
                prompt_version="critic-prompt-v1",
                input_report_sha256="a" * 64,
            ),
            created_at=datetime.now(tz=UTC),
        )
    )
    with client:
        found = client.get(f"/v1/analyses/{ANALYSIS_ID}/critique")
        again = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
    assert found.status_code == 200
    assert found.json()["status"] == "OK"
    assert again.json()["critique"] is None


def test_report_timeline_shot_and_artifact(tmp_path: Path) -> None:
    client, jobs, store = _client(tmp_path)
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
    availability = make_availability(
        chromatic=StageAvailability.COMPLETE,
        motion=StageAvailability.COMPLETE,
        tension=StageAvailability.COMPLETE,
    )
    report = make_report(availability=availability)
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
    with client:
        fetched = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
        window = client.get(
            f"/v1/analyses/{ANALYSIS_ID}/timeline",
            params={"start_ms": 0, "end_ms": 1500, "max_points": 10},
        )
        bad_window = client.get(
            f"/v1/analyses/{ANALYSIS_ID}/timeline",
            params={"start_ms": 10, "end_ms": 10, "max_points": 10},
        )
        shot = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{SHOT_ID}")
        missing_shot = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{uuid4()}")
        artifact = client.get(f"/v1/artifacts/{original.artifact_id}")
        missing_artifact = client.get(f"/v1/artifacts/{uuid4()}")
        ranged = client.get(
            f"/v1/artifacts/{original.artifact_id}",
            headers={"Range": "bytes=0-3"},
        )
    assert fetched.status_code == 200
    assert fetched.json()["analysis_id"] == str(ANALYSIS_ID)
    assert window.status_code == 200
    assert len(window.json()["points"]) == 3
    assert bad_window.status_code == 422
    assert shot.status_code == 200
    assert shot.json()["shot"]["shot_id"] == str(SHOT_ID)
    assert missing_shot.status_code == 404
    assert artifact.status_code == 200
    assert artifact.content == b"mp4-bytes"
    assert missing_artifact.status_code == 404
    assert ranged.status_code in {200, 206}


def test_unhandled_error_does_not_leak_paths(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()

    def boom() -> None:
        message = "failed reading /secret/path.mp4"
        raise RuntimeError(message)

    jobs.ping = boom  # type: ignore[method-assign]
    app = create_app(
        settings=_settings(tmp_path),
        jobs=jobs,
        store=MemoryStore(tmp_path),
        ingest=_Ingest(video_record_from_bytes(b"clip")),
        analyze=CreateAnalysis(jobs),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health/ready")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "RESOURCE_STATE"
    assert "/secret/" not in json.dumps(body)


def test_adapter_error_and_unknown_path(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    jobs.fail_reads = True
    client, _jobs, _store = _client(tmp_path, jobs=jobs)
    with client:
        failed = client.get(f"/v1/analyses/{uuid4()}")
        missing = client.get("/does-not-exist")
        wrong = client.post("/health/live")
    assert failed.status_code == 400
    assert failed.json()["code"] == "RESOURCE_STATE"
    assert missing.status_code == 404
    assert wrong.status_code in {404, 405}


def test_ingest_error_on_upload(tmp_path: Path) -> None:
    video = video_record_from_bytes(b"clip")
    ingest = _Ingest(
        video,
        error=ingest_error(
            "MEDIA_EMPTY",
            "upload contains no bytes",
            request_id="req-empty",
            retryable=False,
        ),
    )
    client, _jobs, _store = _client(tmp_path, ingest=ingest)
    with client:
        response = client.post(
            "/v1/videos",
            files={"file": ("clip.mp4", b"bytes", "video/mp4")},
        )
    assert response.status_code == 400
    assert response.json()["code"] == "MEDIA_EMPTY"


def test_lifespan_constructs_postgres_without_injected_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        database_url="postgresql+pg8000://cine:@127.0.0.1:1/missing",
    )
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/health/live").status_code == 200

    class _NoClose:
        def __init__(self, url: str) -> None:
            del url

    monkeypatch.setattr("cine_analyzer.api.app.PostgresJobRepository", _NoClose)
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/health/live").status_code == 200


def test_unconfigured_dependencies_are_unavailable(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    app = create_app(
        settings=_settings(tmp_path),
        jobs=jobs,
        store=None,
        ingest=None,
        analyze=None,
    )
    with TestClient(app) as client:
        missing_store = client.get(f"/v1/analyses/{uuid4()}/report")
        missing_ingest = client.post(
            "/v1/videos",
            files={"file": ("clip.mp4", b"bytes", "video/mp4")},
        )
        missing_analyze = client.post("/v1/analyses", json={"video_id": str(VIDEO_ID)})
    assert missing_store.status_code == 503
    assert missing_ingest.status_code == 503
    assert missing_analyze.status_code == 503

    bare = create_app(settings=_settings(tmp_path))
    with TestClient(bare) as client:
        missing_jobs = client.post("/v1/analyses", json={"video_id": str(VIDEO_ID)})
        live = client.get("/health/live")
    assert missing_jobs.status_code == 503
    assert live.headers["X-Request-ID"]

    app.state.settings = None
    with TestClient(app) as client:
        missing_settings = client.post(
            "/v1/videos",
            files={"file": ("clip.mp4", b"bytes", "video/mp4")},
        )
    assert missing_settings.status_code == 503


def test_create_analysis_maps_ingest_error_and_accepts_config(tmp_path: Path) -> None:
    video = video_record_from_bytes(b"clip")
    jobs = MemoryJobRepository()
    jobs.insert_video(
        VideoRecord(
            metadata=make_video(),
            original_storage_key="aa/" + "a" * 64,
            probe_storage_key="bb/" + "b" * 64,
        )
    )

    class _BoomAnalyze:
        def execute(self, **kwargs: object) -> object:
            del kwargs
            raise ingest_error(
                "SCHEMA_INVALID",
                "unsupported pipeline",
                request_id="req",
                retryable=False,
            )

    app = create_app(
        settings=_settings(tmp_path),
        jobs=jobs,
        store=MemoryStore(tmp_path),
        ingest=_Ingest(video),
        analyze=_BoomAnalyze(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        failed = client.post("/v1/analyses", json={"video_id": str(VIDEO_ID)})
    assert failed.status_code == 422

    client, jobs2, _store = _client(tmp_path)
    jobs2.insert_video(
        VideoRecord(
            metadata=make_video(),
            original_storage_key="aa/" + "a" * 64,
            probe_storage_key="bb/" + "b" * 64,
        )
    )
    with client:
        created = client.post(
            "/v1/analyses",
            json={
                "video_id": str(VIDEO_ID),
                "config": AnalysisConfig().model_dump(mode="json"),
            },
        )
    assert created.status_code == 202


def test_report_and_timeline_failure_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, jobs, store = _client(tmp_path)
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
            analysis_key="9" * 64,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.RUNNING, target=AnalysisState.SUCCEEDED, progress=1.0
    )
    report = make_report()
    report_key = f"analyses/{ANALYSIS_ID.hex}/report.json"
    store.put_bytes(b"{", storage_key=report_key)
    jobs.insert_artifact(make_artifact(kind="analysis_report"), storage_key=report_key)
    row = jobs.get_artifact_by_storage_key(report_key)
    assert row is not None
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=ANALYSIS_ID,
            summary=report.summary,
            availability=report.availability,
            report_artifact_id=row.artifact_id,
            timeline_artifact_id=None,
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
    with client:
        bad_json = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
        no_timeline = client.get(
            f"/v1/analyses/{ANALYSIS_ID}/timeline",
            params={"start_ms": 0, "end_ms": 1000, "max_points": 10},
        )
        missing_analysis_timeline = client.get(
            f"/v1/analyses/{uuid4()}/timeline",
            params={"start_ms": 0, "end_ms": 1000, "max_points": 10},
        )
        shot = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{SHOT_ID}")
    assert bad_json.status_code == 404
    assert no_timeline.status_code == 404
    assert missing_analysis_timeline.status_code == 404
    assert shot.status_code == 404

    monkeypatch.setattr(
        "cine_analyzer.api.routes.AnalysisConfig",
        lambda: tiny_config(max_upload_bytes=4),
    )
    with client:
        too_large = client.post(
            "/v1/videos",
            files={"file": ("clip.mp4", b"12345", "video/mp4")},
        )
    assert too_large.status_code == 413


def test_artifact_local_path_failure_and_shot_not_ready(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)

    def missing_path(_storage_key: str) -> Path:
        raise AdapterError("ARTIFACT_MISSING", "gone", retryable=False)

    store.local_path = missing_path  # type: ignore[method-assign]
    original = make_artifact(artifact_id=uuid4(), kind="original", media_type="video/mp4")
    store.blobs["orig/key"] = b"mp4-bytes"
    jobs.insert_artifact(original, storage_key="orig/key")
    jobs.insert_video(
        VideoRecord(
            metadata=make_video(),
            original_storage_key="aa/" + "a" * 64,
            probe_storage_key="bb/" + "b" * 64,
        )
    )
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="8" * 64,
            state=AnalysisState.QUEUED,
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
    app = create_app(
        settings=_settings(tmp_path),
        jobs=jobs,
        store=store,
        ingest=_Ingest(video_record_from_bytes(b"clip")),
        analyze=CreateAnalysis(jobs),
    )
    with TestClient(app) as client:
        failed = client.get(f"/v1/artifacts/{original.artifact_id}")
        not_ready_shot = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{SHOT_ID}")
        missing_report_summary = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
    assert failed.status_code == 404
    assert not_ready_shot.status_code == 409
    assert missing_report_summary.status_code == 409


def test_deps_mint_request_id_and_reject_bad_settings() -> None:
    class _State:
        pass

    class _App:
        state = _State()

    class _Request:
        app = _App()
        state = _State()

    request = _Request()
    minted = request_id_of(request)  # type: ignore[arg-type]
    assert minted
    request.app.state.settings = "nope"
    with pytest.raises(ApiError) as caught:
        settings_of(request)  # type: ignore[arg-type]
    assert caught.value.status_code == 503


def test_report_timeline_and_shot_missing_pieces(tmp_path: Path) -> None:
    client, jobs, store = _client(tmp_path)
    jobs.insert_video(
        VideoRecord(
            metadata=make_video(),
            original_storage_key="aa/" + "a" * 64,
            probe_storage_key="bb/" + "b" * 64,
        )
    )
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="7" * 64,
            state=AnalysisState.QUEUED,
        )
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.QUEUED, target=AnalysisState.RUNNING
    )
    jobs.set_analysis_state(
        ANALYSIS_ID, expected=AnalysisState.RUNNING, target=AnalysisState.SUCCEEDED, progress=1.0
    )
    missing_id = uuid4()
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
    with client:
        missing_report = client.get(f"/v1/analyses/{uuid4()}/report")
        not_ready_report = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
        missing_job_timeline = client.get(
            f"/v1/analyses/{uuid4()}/timeline",
            params={"start_ms": 0, "end_ms": 10, "max_points": 2},
        )
        shot_without_summary = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{SHOT_ID}")
    assert missing_report.status_code == 404
    assert not_ready_report.status_code == 409
    assert missing_job_timeline.status_code == 404
    assert shot_without_summary.status_code == 409

    report = make_report()
    report_key = f"analyses/{ANALYSIS_ID.hex}/report.json"
    store.put_bytes(report.model_dump_json().encode("utf-8"), storage_key=report_key)
    jobs.insert_artifact(make_artifact(kind="analysis_report"), storage_key=report_key)
    row = jobs.get_artifact_by_storage_key(report_key)
    assert row is not None
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=ANALYSIS_ID,
            summary=report.summary,
            availability=report.availability,
            report_artifact_id=uuid4(),
            timeline_artifact_id=uuid4(),
        )
    )
    with client:
        missing_artifact = client.get(f"/v1/analyses/{ANALYSIS_ID}/report")
        missing_timeline_blob = client.get(
            f"/v1/analyses/{ANALYSIS_ID}/timeline",
            params={"start_ms": 0, "end_ms": 10, "max_points": 2},
        )
        missing_shot_in_report = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{missing_id}")
        missing_shot_artifact = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{SHOT_ID}")
    assert missing_artifact.status_code == 404
    assert missing_timeline_blob.status_code == 404
    assert missing_shot_in_report.status_code == 404
    assert missing_shot_artifact.status_code == 404

    timeline_key = f"analyses/{ANALYSIS_ID.hex}/timeline.json"
    store.put_bytes(b"{", storage_key=timeline_key)
    jobs.insert_artifact(
        make_artifact(artifact_id=uuid4(), kind="timeline"), storage_key=timeline_key
    )
    timeline_row = jobs.get_artifact_by_storage_key(timeline_key)
    assert timeline_row is not None
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=ANALYSIS_ID,
            summary=report.summary,
            availability=report.availability,
            report_artifact_id=row.artifact_id,
            timeline_artifact_id=timeline_row.artifact_id,
        )
    )
    jobs.save_shots(
        ANALYSIS_ID,
        (
            ShotIntervalRecord(
                shot_id=missing_id,
                analysis_id=ANALYSIS_ID,
                shot_index=1,
                start_ms=0,
                end_ms=10,
            ),
        ),
    )
    with client:
        bad_timeline = client.get(
            f"/v1/analyses/{ANALYSIS_ID}/timeline",
            params={"start_ms": 0, "end_ms": 10, "max_points": 2},
        )
        shot_not_in_json = client.get(f"/v1/analyses/{ANALYSIS_ID}/shots/{missing_id}")
        cancel_ok = client.post(f"/v1/analyses/{ANALYSIS_ID}/cancel")
    assert bad_timeline.status_code == 404
    assert shot_not_in_json.status_code == 404
    assert cancel_ok.status_code == 200

    original_load = jobs.load_job

    def vanish(_analysis_id: UUID) -> object:
        jobs.load_job = original_load  # type: ignore[method-assign]
        return None

    def keep(analysis_id: UUID, now: object) -> object:
        del now
        return jobs.get_analysis(analysis_id)

    jobs.request_cancel = keep  # type: ignore[method-assign]
    jobs.load_job = vanish  # type: ignore[method-assign]
    with client:
        vanished = client.post(f"/v1/analyses/{ANALYSIS_ID}/cancel")
    assert vanished.status_code == 404


def test_metrics_snapshot_and_inflight_failure(tmp_path: Path) -> None:
    client, jobs, _store = _client(tmp_path)
    with client:
        ok = client.get("/metrics")
        jobs.fail_reads = True
        degraded = client.get("/metrics")
    assert ok.status_code == 200
    assert ok.json()["gauges"][0]["name"] == "analysis_active_jobs"
    assert degraded.status_code == 200
    assert degraded.json()["gauges"][0]["value"] == 0


def test_ready_fails_when_celery_broker_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cine_analyzer.application.errors import AdapterError

    def _down(_url: str) -> None:
        raise AdapterError("RESOURCE_NOT_READY", "broker", retryable=True, stage="control")

    monkeypatch.setattr("cine_analyzer.api.routes.ping_broker", _down)
    jobs = MemoryJobRepository()
    app = create_app(
        settings=Settings(
            artifact_root=tmp_path / "artifacts",
            execution_backend="celery",
            redis_url="redis://127.0.0.1:6379/0",
        ),
        jobs=jobs,
        store=MemoryStore(tmp_path),
        ingest=_Ingest(video_record_from_bytes(b"clip")),
        analyze=CreateAnalysis(jobs),
    )
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
