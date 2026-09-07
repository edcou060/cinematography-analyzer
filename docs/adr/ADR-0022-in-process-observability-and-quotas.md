# ADR-0022: In-process observability, bounded cleanup, and in-flight quotas

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none (ADR-0003, ADR-0004, and ADR-0019 remain in force)

## Context

Phase 11 requires traces, metrics, health, hostile-media controls, retention,
and backpressure without adding product features. Prometheus, OpenTelemetry
SDKs, and psutil would expand the base install and the licence/SBOM surface.
IDs in metric labels would explode cardinality. Cleanup that accepts arbitrary
paths would turn retention into a deletion oracle.

## Decision

Observability stays in-process:

- Structured JSON logs keep the documented field vocabulary. Host paths,
  filenames, and stderr values are redacted before render. Request id is bound
  as `trace_id` on API work and copied onto `StageCommand.trace_id`.
- Counters and millisecond histograms live in a process-local registry. Label
  names and values are closed sets. Analysis, video, and artifact ids stay in
  logs and traces, never in metric labels.
- Spans are `span.closed` log events at request/stage/batch granularity.
  Queue wait is `now - StageCommand.requested_at`. Compute is the leased stage
  body. There are no per-frame spans.
- `GET /health/live` is process liveness. `GET /health/ready` pings PostgreSQL
  and, when `execution_backend=celery`, pings Redis. Missing `redis` extra is
  unreadiness, not a base-install dependency. Worker readiness is a CLI check
  against the artifact root and, for GPU role, the process-local detector.
- `GET /metrics` returns a JSON snapshot of the in-process registry plus
  `analysis_active_jobs`. No Prometheus server is started.

Security and cost controls:

- In-flight quota (`CINE_MAX_INFLIGHT_ANALYSES`) is enforced on new analysis
  identities at the API. Reuse of an existing key is not blocked. Over quota
  is `RESOURCE_LIMIT` and HTTP 429.
- Disk headroom (`CINE_MIN_FREE_BYTES`) is checked at ingest before streaming
  into the store. Shortfall is `RESOURCE_DISK`.
- Cleanup may delete files only under generated prefixes `tmp` and
  `quarantine` beneath `artifact_root`, or a canonical blob after
  `canonical_path` resolves a storage key. Broad, absolute, or `..` prefixes
  are refused.
- Media subprocesses keep argument arrays, `shell=False`, timeouts, bounded
  output, and process-group kill. On Unix they also apply conservative rlimits
  in the child. Windows skips `preexec_fn`.

The JPEG decode cache is an internal, per-report `contextvars` memo of sample
bytes. It is not hashed configuration and does not change metric formulas.

## Alternatives considered

**Prometheus client plus a sidecar scrape endpoint.** Rejected for the base
install: extra dependency and operational surface before a measured need.

**OpenTelemetry exporters.** Rejected: same reason; traces are already
propagated as `trace_id` on commands.

**psutil for RSS.** Rejected: `resource.getrusage` is in the stdlib.

**Cleanup by glob or operator-supplied absolute path.** Rejected: hostile
retention.

**In-flight quota inside `CreateAnalysis`.** Rejected for Profile A CLI, which
has no multi-tenant queue. The API is the backpressure boundary.

## Consequences

Easier: one metrics JSON to inspect; cleanup cannot escape `artifact_root`;
Celery and local workers share stage timing via `run_leased_stage`.

Harder: operators who want Prometheus must scrape or adapt JSON themselves.
Quota checks are racy under concurrent accepts; they bound load, they do not
serialize it.

## Verification

Unit tests for redaction, bounded labels, quota 429, cleanup refusal, rlimits
kwargs, and JPEG cache hit counts. Integration/golden suites must keep passing
with the same default config hash. `cine-analyzer benchmark` plus
`validate-benchmark` record RTF, RSS, and cache counters.

## Revisit trigger

A requirement to scrape Prometheus remotely, or evidence that in-process
histograms lose too many samples under multi-worker load.
