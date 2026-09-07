# ADR-0002: Ship an in-process local runner before Celery distribution

- Status: Accepted
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

The original concept named both Celery and Ray. Two orchestrators in one system means two retry semantics, two failure taxonomies, two observability surfaces, and no single owner of task state.

There is also a sequencing question. Shot detection is an early sequential dependency: nothing downstream can be planned until boundaries exist. A distributed executor cannot remove that dependency, so standing up brokers and worker pools before the pipeline works end to end buys queueing infrastructure for a pipeline that has nothing to queue.

`docs/architecture/system-design.md` section 3 (AD-02) fixes one orchestration stack per deployment profile. This ADR records which one comes first and what the sequencing costs.

## Decision

One orchestration stack per deployment profile, and the MVP profile uses an in-process local runner: sequential, in one process, no broker, no worker pool.

Celery with Redis arrives in Phase 10 as the distributed profile, behind the same task interface. Both profiles execute identical stage functions; only submission, retry, and state transport differ. Selecting a profile is configuration, not a code path inside a stage.

Every stage is written from the start as if it were remote: idempotent by `(video_sha256, config_hash, pipeline_version, stage_name)`, taking identifiers rather than objects, writing outputs atomically. The local runner is a scheduling choice, never a licence to pass a NumPy array between stages.

Ray is not adopted.

## Alternatives considered

**Celery from Phase 01.** Rejected: adds a broker, worker lifecycle, serialization, and a second failure surface to debug while the metrics themselves are still unproven. It also makes local test runs depend on running services.

**Celery and Ray together.** Rejected outright. Split task ownership with no measured benefit.

**Ray instead of Celery.** Rejected for now: Ray's actor model and object store suit stateful GPU pipelines with heavy data locality, which is a plausible future for this system but not a measured need. Deferred to the revisit trigger.

**FastAPI background tasks as the permanent executor.** Rejected: they run inside the web worker, which contradicts the rule that the API does not execute heavy analysis, and they do not survive a restart.

## Consequences

Easier: Phases 03 to 09 are debuggable in one process with a stack trace and a breakpoint. Tests need no broker. The stage contract gets exercised before the network can hide a violation.

Harder: the local runner offers no parallelism, so early throughput numbers describe sequential execution and must not be compared with post-Phase-10 figures. Two runner implementations must be kept behaviourally equivalent, which needs a shared conformance test rather than trust.

Risk accepted: writing stages "as if remote" is a discipline the local runner cannot enforce. The conformance test is the enforcement.

## Verification

The same analysis over the same input and configuration produces equal measured values under both runners, checked by a conformance test introduced with Phase 10. Before that, `grep` and review confirm no stage function accepts or returns frame data.

## Revisit trigger

Reopen in favour of Ray only if profiling after Phase 10 shows Celery's scheduling or data movement is the dominant cost — concretely, if task overhead and artifact transfer exceed 25 % of wall time on `bench-03-lowlight-handheld` — and a migration plan exists that keeps the stage interface unchanged.
