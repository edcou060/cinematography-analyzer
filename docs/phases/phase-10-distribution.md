# Phase 10 - Celery/Redis distributed execution

## Mission

Replace the local runner as the deployment execution backend while preserving the same application stage interfaces and report results. Redis/Celery transports commands; PostgreSQL remains authoritative.

## Context budget

Read only:

- `AGENTS.md`
- `docs/project-state.md`
- orchestration/idempotency ADRs
- `docs/architecture/system-design.md` sections 2, 6-9, and 11
- `docs/contracts/data-contracts.md` section 10
- `docs/operations/quality-and-operations.md` sections 5-7
- current stage services/repository ports and focused tests
- this phase guide

## Deliverables

- Celery app/configuration and explicit JSON serialization.
- Queue routes for ingest/orchestration, CPU decode, CPU analysis, GPU spatial, and optional critic.
- Small `StageCommand` tasks that call existing application services.
- DAG scheduling after dependencies complete; aggregation waits on database terminal states.
- Idempotent lease-aware retry/cancel behavior.
- Worker lifecycle hooks for one-time model initialization and resource limits.
- Docker Compose Redis, worker CPU, and optional worker GPU profiles.
- One real broker/worker end-to-end smoke and crash/retry test.

## Steps

1. Add Celery/Redis dependency group and pin through the lockfile.
2. Validate command JSON at the worker boundary. Disable pickle/untrusted serializers.
3. Route tasks by declared resource class. GPU tasks cannot land on a generic high-concurrency queue.
4. Keep task functions thin: bind context, acquire lease, invoke stage service, atomically commit, classify failure.
5. Pass only UUIDs, hashes, versions, timestamps, and small metadata. Add a serialized-size test with a strict ceiling.
6. Implement retries only from error taxonomy. Use backoff/jitter/caps and attempt records.
7. Ensure tasks are idempotent before selecting late acknowledgement/re-delivery behavior.
8. Add cooperative cancellation checks between shots/batches/windows.
9. Initialize heavy detector once in the GPU worker process. Fail readiness if weights identity is wrong.
10. Schedule downstream stages from durable states; do not treat Redis result values as authoritative report data.
11. Run local runner and Celery backend against the same fixture/config and compare validated reports, ignoring runtime-only provenance fields.
12. Kill a worker after artifact write/before state commit; prove a retry finishes without duplicate canonical output.

## Required verification

```bash
uv run pytest tests/unit/workers tests/contract/stage_messages tests/integration/celery -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
docker compose up -d postgres redis api worker-cpu
uv run pytest tests/system/test_distributed_smoke.py -q
```

Run the worker-loss scenario and inspect database attempts/artifact metadata. Verify broker payloads contain no frame bytes, arrays, paths tied to one host, or model objects.

## Exit gate

- [ ] Local and Celery runners use the same application services.
- [ ] PostgreSQL, not Redis, determines job/report truth.
- [ ] Messages are strict JSON and below the size ceiling.
- [ ] CPU/GPU queues and concurrency are explicit.
- [ ] Worker loss/retry is idempotent.
- [ ] Cancellation works between bounded chunks.
- [ ] Models initialize once per appropriate worker process.
- [ ] No Ray/Triton/Kubernetes added.
- [ ] `docs/project-state.md` points to Phase 11.

## Cursor prompt

```text
Execute Phase 10 from docs/phases/phase-10-distribution.md. Add Celery/Redis as
an execution adapter around existing stage services, with JSON-only small
commands, PostgreSQL truth, queue routing, leases, bounded retries, cancellation,
and one-time model initialization. Prove equivalence with the local runner and
worker-loss idempotency. Do not add Ray/Triton/Kubernetes. Verify, update, stop.
```
