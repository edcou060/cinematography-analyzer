# Quality, reliability, security, and operations

## 1. Engineering baseline

The repository should be pleasant to clone, test, profile, and review. A production-looking diagram without executable quality gates weakens the portfolio.

### Runtime and packaging

- Python 3.12 baseline.
- `uv` for environment, dependency groups, scripts, and lockfile.
- `pyproject.toml` as the central tool configuration.
- `src/` package layout.
- Ruff for lint and format.
- mypy in strict-enough incremental mode; tighten deliberately.
- pytest, pytest-cov, Hypothesis, and pytest-xdist where safe.
- SQLAlchemy 2 style and Alembic for migrations.
- Structured logging; no `print` in services/workers.

### Reproducible commands

Expose stable commands through `Makefile` or documented `uv run` scripts:

```bash
make bootstrap
make lint
make typecheck
make test
make test-integration
make test-golden
make run-api
make run-worker-cpu
make run-worker-gpu
make run-dashboard
make compose-up
make benchmark
```

Commands must be wrappers around transparent underlying tools, not hidden magic.

## 2. Test pyramid

### Unit tests

Fast, deterministic, no network, no GPU, no real database unless SQLite in memory is the target. Cover formulas, validation, state transitions, config hashing, sampling, palette ordering, normalization, and error mapping.

### Contract tests

Validate each adapter against the same port contract:

- artifact store atomicity/checksum;
- repository lease and compare-and-set behavior;
- detector output shape and coordinate normalization;
- stage command/result serialization;
- API JSON schema snapshots;
- critic output schema and evidence restrictions.

Fakes must model failures, not only successful return values.

### Integration tests

Run subprocess boundaries and infrastructure:

- ffprobe on tiny valid/corrupt/no-audio/rotated/VFR fixtures;
- database migrations from empty state;
- filesystem artifact lifecycle;
- API upload -> local runner -> report;
- Celery eager tests for wiring plus at least one real broker/worker smoke test;
- cancellation between chunks;
- worker crash/retry/idempotency.

### Golden tests

Use small generated or legally redistributable video fixtures. Store expected structural results and tolerant numeric ranges rather than fragile byte-identical JPEGs.

Golden examples:

- two solid colors with a hard cut at exactly 2 seconds;
- fade-to-black transition;
- moving square with locked background;
- translated checkerboard simulating a pan;
- silent video and video with sine/onset impulses;
- letterboxed palette frame;
- no-person spatial result;
- multiple persons with deterministic primary-track selection.

### Performance tests

Mark separately. Never gate every CPU-only pull request on a GPU. Record:

- real-time factor (RTF = analysis\ wall\ seconds / media\ seconds);
- decode frames per second;
- stage wall time and CPU time;
- peak resident memory;
- GPU peak allocated/reserved memory;
- artifact bytes per input minute;
- database query count/latency;
- queue wait and task runtime;
- cache/deduplication hit ratio.

## 3. Verification matrix

| Change | Minimum verification |
| --- | --- |
| Domain formula | unit + property test + metric card update |
| Pydantic contract | validation tests + JSON-schema snapshot |
| Database model | migration upgrade/downgrade or forward-only policy test |
| FFmpeg command | integration fixtures + timeout/error mapping |
| CV adapter | fake contract test + small real-model smoke test |
| Worker task | idempotency + retry + cancellation test |
| API route | success/error schema + authorization/limit test |
| Dashboard | API mock + manual evidence/sync check |
| Configuration | canonical hash tests + documented default |
| Dependency/model upgrade | lock diff + smoke/golden benchmark + notices review |

## 4. Determinism

Determinism is scoped, not promised universally.

- Fix random seeds for pixel sampling and clustering.
- Record library/model/weight versions and device.
- Use deterministic ordering for shots, samples, tracks, colors, warnings, and artifacts.
- Avoid relying on unordered dictionary/set iteration in serialized output.
- Quantize/round only at presentation boundaries; define JSON precision if snapshots require it.
- Mark GPU algorithms that are nondeterministic and use tolerances.
- Never compare lossy images byte-for-byte across codec/library versions.

An analysis cache hit requires matching media hash, canonical config hash, pipeline version, and relevant capability/model identity.

## 5. Idempotency and retries

Celery can redeliver tasks. Every task therefore follows this pattern:

1. validate the small command envelope;
2. derive the stage idempotency key;
3. acquire a lease or return the existing successful result;
4. heartbeat during bounded chunks;
5. write output to a temporary artifact;
6. validate and atomically promote the artifact;
7. complete the stage using the lease token;
8. on failure, classify and record the error before retry/terminal transition.

### Retry classes

- Retry: transient artifact/database/broker timeouts, selected subprocess resource failures.
- One degraded retry: GPU OOM with a smaller configured batch or resolution.
- Do not retry: corrupt media, unsupported codec/transfer characteristic, schema violations, missing model deployment, invalid config, deterministic decoder crash on the same input.
- Dead-letter/manual review: repeated OOM, worker loss loops, or suspected hostile media.

Use exponential backoff with jitter and caps. Record attempt count and next retry. Never infinite-retry a media file.

## 6. Stage leases and stale workers

A stage lease includes token, worker ID, acquired time, expiry, and heartbeat. Completion performs a compare-and-set on the token. If a worker resumes after its lease expired and another worker completed the stage, its output is an orphan and cannot overwrite the canonical result.

Test:

- two workers race for one stage;
- lease expires mid-work;
- stale worker attempts success;
- cancel requested during lease;
- successful retry reuses or safely replaces temporary artifacts.

## 7. Resource management

### CPU

- Set process concurrency from configuration.
- Cap OpenCV/BLAS/native threads to avoid multiplication by worker count.
- Use bounded chunk sizes and release frame arrays promptly.
- Close `VideoCapture`, PyAV containers, files, and subprocess pipes deterministically.
- Track RSS and recycle workers after a measured number of tasks if a third-party leak exists.

### GPU

- Route GPU work to a dedicated queue.
- Default to one active inference task per GPU.
- Load model once in worker process initialization.
- Use `torch.inference_mode()` and an explicitly selected precision.
- Bound batch by pixels, not only frame count.
- Emptying the CUDA cache on every batch is not a memory-management strategy.
- Record device, precision, batch, resolution, and peak memory.

### Disk/artifacts

- Reserve free-space headroom before extraction.
- Limit derived artifacts per input minute.
- Separate temporary, quarantined, canonical, and expired prefixes.
- Checksum before promotion.
- Clean only known temporary prefixes older than a safe threshold.

## 8. Observability

### Structured log fields

Every service log event should include relevant values from:

`timestamp`, `level`, `service`, `event`, `request_id`, `trace_id`, `analysis_id`, `video_id`, `stage`, `attempt`, `worker_id`, `method_version`, `duration_ms`, `error_code`, `retryable`.

Do not log raw frames, user video metadata beyond operational need, signed URLs, secrets, full critic prompts, or unsafe subprocess output to client-visible logs.

### Metrics

Use bounded-cardinality labels. IDs belong in logs/traces, not Prometheus labels.

- `analysis_jobs_total{state}`
- `analysis_active_jobs`
- `stage_runs_total{stage,state,error_class}`
- `stage_duration_seconds{stage}` histogram
- `queue_wait_seconds{queue}` histogram
- `media_duration_seconds` histogram
- `analysis_realtime_factor{profile}` histogram
- `artifact_write_bytes_total{kind}`
- `artifact_failures_total{operation}`
- `model_inference_batch_seconds{model}`
- `model_oom_total{model}`
- `cache_hits_total{stage}`
- `upload_rejections_total{reason}`

### Tracing

Propagate trace context API -> command -> stage -> artifact/database operations. A trace should show queue wait separately from compute. Do not create spans per frame; use stage/batch granularity.

### Health

- Liveness: event loop/process responds.
- API readiness: database and required settings available; broker policy documented.
- Worker readiness: required artifact store and models loaded for its queue.
- Model readiness: weights checksum matches expected identity.

## 9. Security threat model

The main threat is untrusted, complex binary media processed by native libraries.

### Upload controls

- Stream; do not call `await file.read()` on an unbounded body.
- Enforce request and decompressed/derived size limits.
- Use generated storage names; retain original filename as sanitized metadata only.
- Do not trust MIME or extension.
- Reject unexpected stream counts, extreme dimensions/frame rates/duration, encrypted or unsupported inputs.
- Detect HDR/transfer characteristics and reject/flag outside MVP scope.
- Apply per-user/global quotas and in-flight limits.

### Subprocess controls

- Pass argument arrays with `shell=False`.
- Apply wall timeout and process-group termination.
- Restrict CPU, memory, output file size, open files, and process count where deployment supports it.
- Run media tools as an unprivileged user in an isolated container/profile.
- Disable network access for media workers unless a model download is explicitly part of deployment.
- Never allow input URLs; analyze uploaded/local artifact IDs only.
- Capture bounded stderr; map it to safe error codes.

### Artifact/API controls

- Keep original media outside public static roots.
- Authorize every artifact read.
- Prefer short-lived signed access or API streaming.
- Prevent path traversal by resolving only server-owned artifact IDs.
- Set retention and deletion behavior explicitly.
- Do not expose local filesystem paths in reports.

### Dependency/model supply chain

- Commit lockfile and container digest strategy.
- Download weights during controlled setup/build, not on arbitrary requests.
- Verify weight checksums.
- Generate an SBOM for the release profile.
- Run dependency and container vulnerability checks.
- Record licenses for code and weights.

## 10. Privacy and retention

Video can contain faces, homes, private conversations, or copyrighted material.

- Default to local/private processing in the portfolio demo.
- Document whether uploads leave the host.
- Make the critic opt-in and show exactly which numeric/text fields it receives.
- Do not send frames to the critic in the baseline.
- Configure separate retention for original media, sample frames, debug artifacts, reports, and logs.
- Support deletion by video/analysis ID without unsafe broad filesystem operations.
- Audit deletion and preserve only non-identifying operational aggregates when policy permits.

## 11. Docker Compose production demo

Recommended services:

- `api`
- `worker-cpu`
- `worker-gpu` behind an optional Compose profile
- `postgres`
- `redis`
- `dashboard`
- optional `critic`
- optional metrics stack for a recorded demo

Use one application image with different entrypoints where practical. CPU and GPU extras may require separate images to keep the default small.

Container rules:

- non-root user;
- read-only root filesystem where possible;
- writable mounted artifact/temp directories only;
- health checks;
- explicit CPU/memory limits in demo documentation;
- secrets from environment/secret mount, never image layers;
- migrations run as a one-shot controlled command;
- model weights mounted or baked with checksum, not downloaded per job.

## 12. CI pipeline

### Pull request

1. lockfile consistency;
2. Ruff lint/format;
3. mypy;
4. unit and contract tests with coverage;
5. migration smoke test;
6. CPU integration/golden fixtures;
7. package build;
8. dependency/license/security scans appropriate to the release model.

### Main/nightly

- full Compose smoke test;
- real broker/worker crash test;
- performance regression suite;
- optional GPU adapter smoke test on self-hosted hardware;
- generated API/schema documentation drift check;
- container build and SBOM.

Never put large model weights or private film clips in CI caches without a deliberate policy.

## 13. Performance methodology

Do not publish “fast” without a repeatable benchmark.

### Benchmark corpus

Include at least:

- 60-second 1080p H.264 SDR clip;
- 5-minute 1080p clip;
- high-cut and long-take variants;
- no-audio and stereo-audio variants;
- optional 4K stress clip;
- known unsupported media for rejection latency.

### Benchmark profiles

- CPU core only: probe, shots, sampling, chromatics, audio.
- CPU plus detector on CPU, if usable.
- single GPU spatial adapter.
- local runner versus Celery single-host overhead.
- cold model start versus warm job.

### Report template

```text
Commit / image digest:
Hardware / OS / driver:
Input identity and media properties:
Configuration hash:
Cold or warm:
Stage wall times:
Queue times:
Peak RSS / GPU memory:
Artifact bytes:
End-to-end RTF:
Metric/golden status:
Known caveats:
```

Optimize only after a flame graph/stage profile identifies a dominant cost. Candidate optimizations are ordered decode, fewer seeks, batched inference, contiguous arrays, native thread control, sample-density changes with accuracy evaluation, hardware decode, and model serving.

## 14. Profiling toolkit

- coarse stage timers always on;
- `cProfile` or `py-spy` for Python call costs;
- VizTracer for concurrency/event timing when needed;
- `tracemalloc` for Python allocations;
- process RSS via `psutil`;
- PyTorch profiler and CUDA memory stats for GPU stage;
- FFmpeg benchmark/progress data for decode;
- database query timing and `EXPLAIN` for report endpoints.

Never leave invasive profiling enabled in default production paths.

## 15. Failure drills

Before the release demo, prove behavior when:

- upload disconnects mid-stream;
- file hash already exists;
- ffprobe times out;
- decoder returns no frame for one requested timestamp;
- chromatic task fails on one shot;
- GPU worker is unavailable;
- GPU inference raises OOM;
- Redis restarts;
- API restarts while jobs run;
- worker dies after writing output but before committing state;
- artifact checksum mismatches;
- cancellation arrives during a chunk;
- critic service is unavailable;
- disk free space drops below reserve.

The expected result is specified in a test or runbook, not improvised during the demo.

## 16. Runbook skeleton

For every alert/failure class document:

1. user-visible symptom;
2. relevant safe error code;
3. log query/trace/metric to inspect;
4. likely causes;
5. safe diagnostic commands;
6. recovery action;
7. whether tasks may be retried;
8. data integrity check;
9. escalation/revisit trigger.

## 17. Release gates

### Technical

- Clean clone bootstrap succeeds from the README.
- Lockfile and Compose deployment are reproducible.
- Unit, contract, integration, and golden suites pass.
- At least one failure drill is automated for each critical boundary.
- No secrets, private clips, generated frames, local DBs, or weights are committed.
- Public report schema and API docs match implementation.
- License choice and third-party notices are explicit.

### Product

- User can upload, see progress, inspect shots, view palette/lightness/composition evidence, and understand unavailable stages.
- Tension curve shows components and caveat.
- AI critique is clearly optional/interpreted.
- Dashboard remains usable when spatial or audio analysis is absent.

### Portfolio

- Architecture diagram matches deployed system.
- README explains tradeoffs, not just libraries.
- Benchmark report includes hardware and configuration.
- Short demo uses legally shareable footage.
- One incident/failure scenario is shown.
- One before/after profiling result demonstrates a measured optimization.
