# Phase 11 - Reliability, observability, security, and performance

## Mission

Make failure and cost visible, harden hostile-media boundaries, execute failure drills, and optimize one measured bottleneck. Do not add product features.

## Context budget

Read only:

- `docs/project-state.md`
- security/operations ADRs
- `docs/operations/quality-and-operations.md`
- `docs/architecture/system-design.md` sections 9, 18, and 19
- current ingestion/worker/artifact/repository code and focused tests
- this phase guide

## Deliverables

- Structured logs with request/trace/analysis/stage context and redaction.
- Stage/queue/resource/application metrics with bounded labels.
- Cross-service trace propagation at request/stage/batch granularity.
- Liveness/readiness checks for API and workers.
- Upload/subprocess/artifact security controls and documented threat model.
- Retention/cleanup job scoped to known IDs/prefixes.
- Failure-drill tests/runbook.
- Reproducible benchmark harness and a baseline report.
- One profiling-backed optimization with before/after results.

## Steps

1. Audit log fields and external errors for local paths, raw filenames, stderr, secrets, prompts, and high-cardinality labels.
2. Instrument API acceptance, queue wait, stage runtime, artifact I/O, model batches/OOM, cache reuse, and end-to-end real-time factor.
3. Propagate trace IDs through strict commands. Avoid spans per frame.
4. Implement health checks that distinguish liveness, dependency readiness, and model readiness.
5. Enforce upload bytes/duration/dimensions/streams/codec/SDR rules at multiple layers.
6. Isolate FFmpeg/ffprobe with non-shell args, timeouts, bounded output, process-group termination, unprivileged container, and resource limits supported by the platform.
7. Verify artifact authorization/path resolution and retention deletion by ID. Cleanup can touch only generated known prefixes.
8. Add quotas/in-flight limits and backpressure behavior.
9. Execute the failure drills in the operations guide. Automate the highest-risk cases.
10. Run benchmark corpus cold/warm, record hardware/config/commit/stage times/RSS/GPU/artifact bytes.
11. Profile the dominant stage. Choose one optimization only after evidence.
12. Re-run golden correctness and benchmark. Reject optimizations that exceed the accuracy/stability budget.
13. Add a runbook for every observed failure code.

## Required verification

```bash
uv run pytest tests/security tests/failure tests/integration tests/golden -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src apps
uv run cine-analyzer benchmark --manifest fixtures/benchmark/manifest.yaml --output build/benchmark.json
uv run cine-analyzer validate-benchmark build/benchmark.json
```

Also run dependency/container/SBOM checks selected by the repository policy and record exact versions/results. Manually inspect a trace and metrics dashboard for one job.

## Exit gate

- [ ] External errors/logs do not leak sensitive internals.
- [ ] Metrics labels are bounded and useful.
- [ ] One trace separates queue wait from compute.
- [ ] Hostile/unsupported media fails within configured limits.
- [ ] Cleanup cannot target broad/unresolved paths.
- [ ] Critical failure drills have expected outcomes.
- [ ] Baseline benchmark is reproducible.
- [ ] One optimization has measured before/after data and unchanged golden status.
- [ ] `docs/project-state.md` points to Phase 12 or directly Phase 13 if critic is skipped.
