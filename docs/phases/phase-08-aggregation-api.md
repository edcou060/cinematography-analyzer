# Phase 08 - Aggregation, PostgreSQL, and report API

## Mission

Promote the working local pipeline into a durable control plane: PostgreSQL state, migrations, strict aggregation, asynchronous analysis creation, status, cancellation intent, and report/timeline/evidence endpoints. Heavy work still uses the local runner in a separate process/command.

## Context budget

Read only:

- `docs/project-state.md`
- database/API/state ADRs
- `docs/architecture/system-design.md` sections 4, 6, 10-13
- `docs/contracts/data-contracts.md` sections 9-14
- `docs/operations/quality-and-operations.md` sections 3, 5-9
- current application ports and report tests
- this phase guide

## Deliverables

- SQLAlchemy models and Alembic migrations for core tables.
- PostgreSQL repository adapter with compare-and-set transitions and stage leases.
- Aggregator that validates required terminal states and produces partial reports honestly.
- FastAPI endpoints for video, analysis, status, cancellation, report, timeline windows, shot detail, and artifacts.
- API problem/error model, request/trace IDs, and OpenAPI schema snapshot.
- Separate local worker/runner command that claims queued work; API never executes heavy analysis.
- Integration tests with PostgreSQL and filesystem artifact store.

## Steps

1. Map domain concepts to relational tables; keep large arrays/media in artifacts.
2. Write the initial migration and test upgrade from an empty database. Do not use `create_all` for runtime migration.
3. Implement repository transactions for video/analysis deduplication, stage lease acquire/heartbeat/complete/fail, cancellation request, and terminal state.
4. Test races: duplicate analysis creation, two stage claimants, stale completion, retry attempt.
5. Implement the aggregator. Required stage failure -> failed analysis; optional stage failure -> partial; no-audio -> successful unavailable audio.
6. Implement upload streaming and reuse the Phase 03 ingestion service.
7. Return `202` for analysis creation. Separate video identity from config identity.
8. Implement status/progress from stage weights/states.
9. Implement windowed/downsampled timeline queries and authorized range-capable artifacts.
10. Map internal exceptions to stable safe errors; keep paths/stderr out of responses.
11. Generate/snapshot OpenAPI and public report JSON schema.
12. Run API and local worker separately in integration smoke tests.

## Required verification

```bash
uv run alembic upgrade head
uv run pytest tests/unit/aggregation tests/contract/api tests/integration/postgres tests/integration/api -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run cine-analyzer export-openapi --check
```

Run a manual smoke: start API and local worker, upload the tiny clip, receive 202, observe state transitions, fetch report and a bounded timeline window, then repeat the analysis request and prove reuse.

## Exit gate

- [ ] API process performs no heavy CV/audio analysis.
- [ ] Database is authoritative and migrations are tested.
- [ ] Duplicate/racing requests are safe.
- [ ] Stale leases cannot overwrite canonical state.
- [ ] Partial reports expose availability/reasons.
- [ ] Public schemas are snapshotted.
- [ ] Timeline/artifact endpoints are bounded and authorized.
- [ ] `docs/project-state.md` points to Phase 09.
