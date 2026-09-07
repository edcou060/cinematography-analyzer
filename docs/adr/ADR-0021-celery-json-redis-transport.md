# ADR-0021: Celery JSON transport with Redis; PostgreSQL remains job truth

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none (ADR-0002, ADR-0003, ADR-0004, and ADR-0019 remain in force)

## Context

Phase 10 replaces the local PostgreSQL poll loop as the **deployment** execution
backend. ADR-0002 already required one orchestrator per profile and identical
stage functions. ADR-0003 forbids treating Redis or a Celery result backend as
job or report truth. ADR-0004 forbids frames, arrays, models, and host paths in
queue payloads. ADR-0019 left Celery as a revisit trigger.

Celery's default pickle serializer is an untrusted-code path. GPU spatial work
must not share a high-concurrency CPU queue. A real Ultralytics detector is
still gated (ADR-0007); the GPU worker still has to prove one-time init and
weights-identity failure.

## Decision

The deployment profile (`CINE_EXECUTION_BACKEND=celery`) submits `StageCommand`
JSON to Redis through Celery. The local poll worker remains the default profile
and the conformance baseline. Both call `run_leased_stage` and the existing
sampling, report, and aggregate application services.

Rules:

- Serializers are JSON only. Pickle and other content types are not accepted.
- Queue names are explicit: `ingest`, `cpu_decode`, `cpu_analysis`,
  `gpu_spatial`, `critic`. Stage routing never places `spatial` on a CPU
  analysis queue.
- Messages are `StageCommand` objects under `QUEUE_PAYLOAD_MAX_BYTES`.
- Downstream stages are enqueued only after PostgreSQL records a terminal
  attempt for the predecessor. Aggregation reads the report artifact and job
  rows, never a Celery result value. `task_ignore_result` is on; no result
  backend is configured as truth.
- Retries follow the SafeError taxonomy, with bounded exponential backoff and
  jitter. Cooperative cancel is checked between stages and between shots.
- Celery and redis-py live in the `celery` dependency group, not the base
  install. Domain code does not import Celery.
- The GPU worker process initializes the configured detector once. Backend
  `ultralytics` fails readiness until the gated extra exists. A configured
  weights digest that does not match the fake-detector identity fails
  readiness. Fake spatial measurement still runs inside the CPU `report` stage
  (ADR-0014); `gpu_spatial` is isolated for the real detector path.
- Docker Compose runs postgres, redis, api, and `worker-cpu`. `worker-gpu` is
  an optional profile. Ray, Triton, and Kubernetes are not added.

## Alternatives considered

**Celery result backend as aggregation input.** Rejected: ADR-0003.

**Pickle for Pydantic models.** Rejected: code execution on the worker.

**Split spatial out of `report` in this phase.** Rejected: that is a pipeline
contract change; isolation of the GPU queue does not require it while the
detector is fake.

**Ray or a second orchestrator.** Rejected: ADR-0002.

## Consequences

Easier: API processes stay free of CV libraries; CPU and GPU concurrency are
independent; worker loss redelivers a small JSON command against durable state.

Harder: two submission paths must stay equivalent on measured report fields.
Operators must run Redis and the `celery` extra for Profile B.

## Verification

JSON serializer and payload-ceiling tests; GPU-vs-CPU routing tests; local vs
Celery report comparison ignoring runtime provenance; artifact-write-then-crash
retry without duplicate canonical bytes; Compose smoke against a real broker.

## Revisit trigger

A licensed detector extra (ADR-0007) that must run on `gpu_spatial`, or
profiling after Phase 10 showing Celery overhead above the ADR-0002 Ray
threshold.
