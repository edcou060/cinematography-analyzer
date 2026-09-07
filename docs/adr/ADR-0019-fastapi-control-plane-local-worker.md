# ADR-0019: Thin FastAPI control plane and a separate local worker

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

The API must accept uploads, create analyses, report status, and serve reports
without decoding video or loading CV models (system design §6 and §12). FastAPI
background tasks were already rejected in ADR-0002. Celery arrives in Phase 10.
The local runner already exists as sequential CLI stages; it needs a process
that claims queued PostgreSQL work.

Public HTTP shapes are a contract: `202` on analysis creation, SafeError
problem details, OpenAPI snapshot, bounded timeline windows, and artifact
streaming that never echoes filesystem paths.

## Decision

FastAPI owns `/v1/videos`, `/v1/analyses`, status, cancel, report, windowed
timeline, shot detail, artifacts, and health. It streams uploads into the
existing ingest use case and inserts a `QUEUED` analysis. It never imports
OpenCV, PyAV, PySceneDetect, or report-stage analyzers.

`cine-analyzer worker` is a separate command. It compare-and-sets `QUEUED` to
`RUNNING`, acquires stage leases, runs the existing sampling and report
entry points, then aggregates. `cine-analyzer serve` binds Uvicorn to the API
app only.

Aggregator rules:

- Required stage failure (`sampling` or `report`) → analysis `FAILED`
- Optional pillar issues → `PARTIAL` (chromatic/motion unavailable or partial;
  audio extract failure when the source has audio; tension unavailable)
- Spatial `UNAVAILABLE` with backend `none` is not a failure
- No audio stream (`NO_AUDIO`) → successful analysis with audio unavailable
- Cooperative cancel between stages → `CANCELED`

Artifact reads are authorized by possession of the server-issued UUID. There
are no user accounts yet. Range requests are served for original media.
Timeline queries require `start_ms`, `end_ms`, and `max_points` (capped).

Request IDs come from `X-Request-ID` or a generated UUID. Client errors use
`SafeError` only.

## Alternatives considered

**Run analysis inside FastAPI `BackgroundTasks`.** Rejected: ADR-0002; work dies
with the web process and loads models into API workers.

**Celery in this phase.** Rejected: Phase 10. The worker polls PostgreSQL.

**Combine upload and analysis in one endpoint.** Rejected: video identity must
stay separate from config identity so repeats do not duplicate media.

## Consequences

Easier: the CLI `analyze` path stays SQLite-local; the HTTP path is restartable
and testable with TestClient plus a worker `--once` flag.

Harder: two processes must share artifact root and database URL. OpenAPI and
SafeError snapshots are now part of the public contract.

## Verification

A subprocess import of `cine_analyzer.api.app` does not load `cv2`, `av`, or
`scenedetect`. Integration smoke: upload, `202`, worker `--once`, fetch report
and a bounded timeline, repeat analysis and observe reuse. `export-openapi
--check` matches the committed snapshot.

## Revisit trigger

Authentication, signed artifact URLs, or Celery submission replace UUID
capability tokens or the poll loop; record that in a new ADR.
