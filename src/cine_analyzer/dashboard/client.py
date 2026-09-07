"""Typed HTTP client for the public control plane. No Streamlit, no workers."""

from collections.abc import Mapping
from typing import BinaryIO, Final
from uuid import UUID

import httpx

from cine_analyzer.api.schemas import (
    AnalysisAccepted,
    AnalysisCreateRequest,
    HealthResponse,
    TimelineWindowResponse,
    VideoAccepted,
)
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.errors import SafeError
from cine_analyzer.domain.jobs import AnalysisStatusResponse
from cine_analyzer.domain.report import AnalysisReport, Critique, ShotAnalysis

__all__ = [
    "DASHBOARD_TIMELINE_MAX_POINTS",
    "IDEMPOTENT_METHODS",
    "AnalyzerClient",
    "DashboardClientError",
]

DASHBOARD_TIMELINE_MAX_POINTS: Final = 500
IDEMPOTENT_METHODS: Final = frozenset({"GET", "HEAD"})
_RETRYABLE_STATUS: Final = frozenset({502, 503, 504})
_MAX_ATTEMPTS: Final = 3


class DashboardClientError(Exception):
    """HTTP or transport failure mapped to a SafeError body."""

    def __init__(self, safe: SafeError, status_code: int) -> None:
        self.safe = safe
        self.status_code = status_code
        super().__init__(safe.message)


class AnalyzerClient:
    """Validate every payload with public Pydantic models. Retry GET only."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout_s: float = 30.0,
        upload_timeout_s: float = 600.0,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        self._owns = client is None
        self._upload_timeout_s = upload_timeout_s
        self._max_attempts = max(1, max_attempts)
        self._http = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            follow_redirects=False,
        )

    def close(self) -> None:
        """Close an owned transport. Injected clients are left open."""
        if self._owns:
            self._http.close()

    def __enter__(self) -> "AnalyzerClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def live(self) -> HealthResponse:
        """Process liveness."""
        return HealthResponse.model_validate(self._json("GET", "/health/live"))

    def ready(self) -> HealthResponse:
        """Dependency readiness."""
        return HealthResponse.model_validate(self._json("GET", "/health/ready"))

    def upload_video(
        self,
        data: BinaryIO,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> VideoAccepted:
        """Stream an upload. Not retried."""
        payload = self._json(
            "POST",
            "/v1/videos",
            files={"file": (filename, data, content_type)},
            timeout=httpx.Timeout(self._upload_timeout_s),
        )
        return VideoAccepted.model_validate(payload)

    def create_analysis(
        self,
        video_id: UUID,
        config: AnalysisConfig | None = None,
    ) -> AnalysisAccepted:
        """Queue or reuse an analysis. Not retried."""
        body = AnalysisCreateRequest(video_id=video_id, config=config)
        payload = self._json(
            "POST",
            "/v1/analyses",
            json=body.model_dump(mode="json"),
        )
        return AnalysisAccepted.model_validate(payload)

    def get_status(self, analysis_id: UUID) -> AnalysisStatusResponse:
        """Authoritative job status."""
        return AnalysisStatusResponse.model_validate(
            self._json("GET", f"/v1/analyses/{analysis_id}")
        )

    def cancel(self, analysis_id: UUID) -> AnalysisStatusResponse:
        """Request cooperative cancellation. Not retried."""
        return AnalysisStatusResponse.model_validate(
            self._json("POST", f"/v1/analyses/{analysis_id}/cancel")
        )

    def get_report(self, analysis_id: UUID) -> AnalysisReport:
        """Canonical report once aggregation finished."""
        return AnalysisReport.model_validate(
            self._json("GET", f"/v1/analyses/{analysis_id}/report")
        )

    def get_critique(self, analysis_id: UUID) -> Critique:
        """Optional interpretation stored beside the report."""
        return Critique.model_validate(self._json("GET", f"/v1/analyses/{analysis_id}/critique"))

    def get_timeline(
        self,
        analysis_id: UUID,
        *,
        start_ms: int,
        end_ms: int,
        max_points: int = DASHBOARD_TIMELINE_MAX_POINTS,
    ) -> TimelineWindowResponse:
        """Windowed, downsampled tension-proxy series."""
        cap = min(max(1, max_points), DASHBOARD_TIMELINE_MAX_POINTS)
        return TimelineWindowResponse.model_validate(
            self._json(
                "GET",
                f"/v1/analyses/{analysis_id}/timeline",
                params={"start_ms": start_ms, "end_ms": end_ms, "max_points": cap},
            )
        )

    def get_shot(self, analysis_id: UUID, shot_id: UUID) -> ShotAnalysis:
        """One shot's measured metrics."""
        return ShotAnalysis.model_validate(
            self._json("GET", f"/v1/analyses/{analysis_id}/shots/{shot_id}")
        )

    def artifact_url(self, artifact_id: UUID) -> str:
        """URL for an authorized artifact stream. Possession of the UUID is the capability."""
        return f"{str(self._http.base_url).rstrip('/')}/v1/artifacts/{artifact_id}"

    def get_artifact_bytes(self, artifact_id: UUID) -> bytes:
        """Download artifact bytes (evidence images). GET is retried."""
        response = self._send("GET", f"/v1/artifacts/{artifact_id}")
        return response.content

    def _json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, int | str] | None = None,
        json: Mapping[str, object] | None = None,
        files: object | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> object:
        response = self._send(method, path, params=params, json=json, files=files, timeout=timeout)
        return response.json()

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, int | str] | None = None,
        json: Mapping[str, object] | None = None,
        files: object | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        idempotent = method.upper() in IDEMPOTENT_METHODS
        attempts = self._max_attempts if idempotent else 1
        last_error: DashboardClientError | None = None
        for attempt in range(attempts):
            try:
                kwargs: dict[str, object] = {"params": params, "json": json, "files": files}
                if timeout is not None:
                    kwargs["timeout"] = timeout
                response = self._http.request(method, path, **kwargs)  # type: ignore[arg-type]
            except httpx.HTTPError as error:
                last_error = DashboardClientError(
                    SafeError(
                        code="RESOURCE_STATE",
                        message="the control plane could not be reached",
                        retryable=True,
                        stage="control",
                        request_id="dashboard-client",
                    ),
                    503,
                )
                if not idempotent or attempt + 1 >= attempts:
                    raise last_error from error
                continue
            if response.status_code < 400:
                return response
            last_error = _error_from_response(response)
            retry = (
                idempotent
                and last_error.safe.retryable
                and response.status_code in _RETRYABLE_STATUS
                and attempt + 1 < attempts
            )
            if not retry:
                raise last_error
        raise RuntimeError("the control plane returned no response")  # pragma: no cover


def _error_from_response(response: httpx.Response) -> DashboardClientError:
    try:
        payload = response.json()
        safe = SafeError.model_validate(payload)
    except ValueError:
        safe = SafeError(
            code="RESOURCE_STATE",
            message="the request could not be completed",
            retryable=response.status_code >= 500,
            stage="control",
            request_id=response.headers.get("x-request-id", "dashboard-client"),
        )
    return DashboardClientError(safe, response.status_code)
