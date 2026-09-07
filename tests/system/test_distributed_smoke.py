"""Compose/distributed smoke. Requires the API on CINE_API_PUBLIC_URL."""

import os
from pathlib import Path

import httpx
import pytest

from cine_analyzer.domain.report import AnalysisReport


def _base_url() -> str:
    return os.environ.get("CINE_API_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


def _api_is_live() -> bool:
    try:
        response = httpx.get(f"{_base_url()}/health/live", timeout=1.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def test_distributed_upload_completes(video_fixtures: Path) -> None:
    if os.environ.get("CINE_SYSTEM_SMOKE") != "1" and not _api_is_live():
        pytest.skip("distributed API is not running")
    clip = video_fixtures / "two_color_cut.mp4"
    if not clip.is_file():
        pytest.skip("two_color_cut.mp4 fixture is missing")
    base = _base_url()
    with httpx.Client(base_url=base, timeout=120.0) as client:
        with clip.open("rb") as handle:
            uploaded = client.post("/v1/videos", files={"file": ("two_color_cut.mp4", handle)})
        assert uploaded.status_code == 201
        video_id = uploaded.json()["video_id"]
        created = client.post("/v1/analyses", json={"video_id": video_id})
        assert created.status_code == 202
        analysis_id = created.json()["analysis_id"]
        state = "QUEUED"
        for _ in range(120):
            status = client.get(f"/v1/analyses/{analysis_id}")
            assert status.status_code == 200
            state = status.json()["state"]
            if state in {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELED"}:
                break
            import time

            time.sleep(0.5)
        assert state in {"SUCCEEDED", "PARTIAL"}
        report_response = client.get(f"/v1/analyses/{analysis_id}/report")
        assert report_response.status_code == 200
        report = AnalysisReport.model_validate(report_response.json())
        assert report.summary.shot_count >= 1
