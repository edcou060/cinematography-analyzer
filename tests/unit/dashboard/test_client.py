"""Typed client: SafeError mapping and GET-only retries."""

from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from tests.factories import ANALYSIS_ID, ARTIFACT_ID, DIGEST, SHOT_ID, VIDEO_ID, make_report

from cine_analyzer.dashboard.client import (
    DASHBOARD_TIMELINE_MAX_POINTS,
    AnalyzerClient,
    DashboardClientError,
)
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.types import SCHEMA_VERSION

_RETRY = {
    "code": "RESOURCE_STATE",
    "message": "temporarily unavailable",
    "retryable": True,
    "stage": "control",
    "request_id": "retry",
}
_MISSING = {
    "code": "ARTIFACT_MISSING",
    "message": "the requested resource was not found",
    "retryable": False,
    "stage": "control",
    "request_id": "missing",
}


def _client(handler: object) -> AnalyzerClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.Client(transport=transport, base_url="http://analyzer.test")
    return AnalyzerClient("http://analyzer.test", client=http)


def test_live_and_ready_validate_health_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        status = "ok" if request.url.path.endswith("/live") else "unavailable"
        code = 200 if status == "ok" else 503
        return httpx.Response(code, json={"status": status})

    client = _client(handler)
    assert client.live().status == "ok"
    with pytest.raises(DashboardClientError) as caught:
        client.ready()
    assert caught.value.status_code == 503
    assert "could not be completed" in caught.value.safe.message


def test_get_retries_retryable_gateway_statuses_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json=_RETRY)
        return httpx.Response(200, json={"status": "ok"})

    assert _client(handler).live().status == "ok"
    assert calls["n"] == 3


def test_post_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(503, json=_RETRY)

    with pytest.raises(DashboardClientError):
        _client(handler).create_analysis(VIDEO_ID)
    assert calls["n"] == 1


def test_transport_errors_retry_on_get_only() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("offline", request=request)

    client = _client(handler)
    with pytest.raises(DashboardClientError) as caught:
        client.live()
    assert caught.value.safe.retryable is True
    assert calls["n"] == 3

    calls["n"] = 0
    with pytest.raises(DashboardClientError):
        client.cancel(ANALYSIS_ID)
    assert calls["n"] == 1


def test_non_gateway_server_error_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(500, json=_RETRY)

    with pytest.raises(DashboardClientError) as caught:
        _client(handler).get_status(ANALYSIS_ID)
    assert caught.value.status_code == 500
    assert calls["n"] == 1


def test_safeerror_body_is_preserved() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, json=_MISSING)

    with pytest.raises(DashboardClientError) as caught:
        _client(handler).get_report(ANALYSIS_ID)
    assert caught.value.safe.code == "ARTIFACT_MISSING"
    assert caught.value.safe.retryable is False


def test_invalid_error_json_maps_to_a_generic_safeerror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(400, text="not-json")

    with pytest.raises(DashboardClientError) as caught:
        _client(handler).get_shot(ANALYSIS_ID, SHOT_ID)
    assert caught.value.safe.code == "RESOURCE_STATE"
    assert caught.value.safe.retryable is False


def test_upload_create_status_cancel_report_timeline_shot_and_artifact() -> None:
    report = make_report()
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        captured["last"] = f"{request.method} {path}"
        if request.method == "POST" and path == "/v1/videos":
            return httpx.Response(
                201,
                json={
                    "video_id": str(VIDEO_ID),
                    "content_sha256": DIGEST,
                    "reused": False,
                    "duration_ms": 4000,
                    "width": 1920,
                    "height": 1080,
                    "has_audio": False,
                },
            )
        if request.method == "POST" and path == "/v1/analyses":
            return httpx.Response(
                202,
                json={
                    "analysis_id": str(ANALYSIS_ID),
                    "video_id": str(VIDEO_ID),
                    "configuration_hash": DIGEST,
                    "pipeline_version": "0.1.0",
                    "reused": False,
                    "state": AnalysisState.QUEUED.value,
                },
            )
        if request.method == "GET" and path == f"/v1/analyses/{ANALYSIS_ID}":
            return httpx.Response(
                200,
                json={
                    "analysis_id": str(ANALYSIS_ID),
                    "state": AnalysisState.SUCCEEDED.value,
                    "progress": 1.0,
                    "completed_stages": ["sampling", "report", "aggregate"],
                    "active_stages": [],
                    "unavailable_stages": [],
                },
            )
        if request.method == "POST" and path == f"/v1/analyses/{ANALYSIS_ID}/cancel":
            return httpx.Response(
                200,
                json={
                    "analysis_id": str(ANALYSIS_ID),
                    "state": AnalysisState.CANCELED.value,
                    "progress": 0.0,
                    "completed_stages": [],
                    "active_stages": [],
                    "unavailable_stages": [],
                },
            )
        if path == f"/v1/analyses/{ANALYSIS_ID}/report":
            return httpx.Response(200, json=report.model_dump(mode="json"))
        if path == f"/v1/analyses/{ANALYSIS_ID}/critique":
            return httpx.Response(
                200,
                json={
                    "status": "NOT_COMPUTED",
                    "text": None,
                    "model_name": None,
                    "prompt_version": None,
                    "input_report_sha256": None,
                },
            )
        if path == f"/v1/analyses/{ANALYSIS_ID}/timeline":
            captured["max_points"] = request.url.params["max_points"]
            captured["start_ms"] = request.url.params["start_ms"]
            captured["end_ms"] = request.url.params["end_ms"]
            return httpx.Response(
                200,
                json={
                    "analysis_id": str(ANALYSIS_ID),
                    "start_ms": 0,
                    "end_ms": 4000,
                    "max_points": DASHBOARD_TIMELINE_MAX_POINTS,
                    "points": [],
                },
            )
        if path == f"/v1/analyses/{ANALYSIS_ID}/shots/{SHOT_ID}":
            return httpx.Response(200, json=report.shots[0].model_dump(mode="json"))
        if path == f"/v1/artifacts/{ARTIFACT_ID}":
            return httpx.Response(200, content=b"jpeg-bytes")
        return httpx.Response(404, json=_MISSING)

    client = _client(handler)
    uploaded = client.upload_video(BytesIO(b"clip"), filename="clip.mp4")
    created = client.create_analysis(VIDEO_ID, config=AnalysisConfig())
    status = client.get_status(ANALYSIS_ID)
    canceled = client.cancel(ANALYSIS_ID)
    fetched = client.get_report(ANALYSIS_ID)
    critique = client.get_critique(ANALYSIS_ID)
    window = client.get_timeline(ANALYSIS_ID, start_ms=0, end_ms=4000, max_points=2000)
    shot = client.get_shot(ANALYSIS_ID, SHOT_ID)
    payload = client.get_artifact_bytes(ARTIFACT_ID)

    assert uploaded.video_id == VIDEO_ID
    assert created.state is AnalysisState.QUEUED
    assert status.state is AnalysisState.SUCCEEDED
    assert canceled.state is AnalysisState.CANCELED
    assert fetched.schema_version == SCHEMA_VERSION
    assert critique.text is None
    assert window.max_points == DASHBOARD_TIMELINE_MAX_POINTS
    assert captured["max_points"] == str(DASHBOARD_TIMELINE_MAX_POINTS)
    assert captured["start_ms"] == "0"
    assert shot.shot.shot_id == SHOT_ID
    assert payload == b"jpeg-bytes"
    assert client.artifact_url(ARTIFACT_ID).endswith(f"/v1/artifacts/{ARTIFACT_ID}")


def test_owned_client_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        def __init__(self, **kwargs: object) -> None:
            self.closed = False
            self.base_url = kwargs["base_url"]

        def close(self) -> None:
            self.closed = True

        def request(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr("cine_analyzer.dashboard.client.httpx.Client", Fake)
    with AnalyzerClient("http://example.invalid") as owned:
        assert owned.live().status == "ok"
    assert owned._http.closed is True


def test_injected_client_is_left_open() -> None:
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"status": "ok"})),
        base_url="http://analyzer.test",
    )
    injected = AnalyzerClient("http://analyzer.test", client=http)
    injected.close()
    assert http.get("/health/live").status_code == 200
    http.close()


def test_retryable_false_on_gateway_status_is_not_retried() -> None:
    calls = {"n": 0}
    body = dict(_RETRY)
    body["retryable"] = False

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(502, json=body)

    with pytest.raises(DashboardClientError):
        _client(handler).get_status(ANALYSIS_ID)
    assert calls["n"] == 1


def test_unknown_json_error_body_is_generic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(422, json={"unexpected": True})

    with pytest.raises(DashboardClientError) as caught:
        _client(handler).get_report(uuid4())
    assert caught.value.safe.message == "the request could not be completed"
