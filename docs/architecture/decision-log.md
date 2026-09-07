# Architecture decision log

Create one Markdown ADR per consequential decision in `docs/adr/` using the template below. Never rewrite history: supersede an ADR with a new ADR.

## Initial decisions

Accepted in Phase 00 on 2026-09-05.

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0001 | Use “shot” for detected edit intervals | Accepted | [`ADR-0001`](../adr/ADR-0001-shots-not-narrative-scenes.md) |
| ADR-0002 | Use a local runner before Celery distribution | Accepted | [`ADR-0002`](../adr/ADR-0002-local-runner-before-celery.md) |
| ADR-0003 | PostgreSQL is authoritative; Redis is transport | Accepted | [`ADR-0003`](../adr/ADR-0003-postgres-authoritative-redis-transport.md) |
| ADR-0004 | Queue payloads contain references, not frame bytes | Accepted | [`ADR-0004`](../adr/ADR-0004-queue-payloads-are-references.md) |
| ADR-0005 | Separate deterministic metrics from optional LLM prose | Accepted | [`ADR-0005`](../adr/ADR-0005-measurement-separate-from-interpretation.md) |
| ADR-0006 | Use integer milliseconds at persisted boundaries | Accepted | [`ADR-0006`](../adr/ADR-0006-integer-milliseconds.md) |
| ADR-0007 | License-gate the Ultralytics adapter | Accepted; release path deferred to the project owner, blocking a real detector extra | [`ADR-0007`](../adr/ADR-0007-ultralytics-license-gate.md) |
| ADR-0008 | Public Apache-2.0 release, detector-neutral base install | Accepted | [`ADR-0008`](../adr/ADR-0008-release-model-and-license.md) |

Phase 04 added two ADRs. Extraction uses PyAV rather than FFmpeg seeks (ADR-0009). Shot-detector working width, thresholds, and debug persistence are hashed `ShotsConfig` fields (ADR-0010); that change invalidates pre-Phase-04 default config hashes.

Phase 05 added two ADRs. Chromatic letterbox, MiniBatchKMeans, Delta-E merge, and lighting-key thresholds are hashed `ChromaticConfig` fields (ADR-0011); that change invalidates pre-Phase-05 default config hashes. Lab conversion uses the existing `opencv-python` wheel and sklearn MiniBatchKMeans; `opencv-python-headless` is not added (ADR-0012).

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0009 | Ordered sample extraction uses PyAV | Accepted | [`ADR-0009`](../adr/ADR-0009-pyav-ordered-extraction.md) |
| ADR-0010 | Hashed shot-detector parameters are config fields | Accepted | [`ADR-0010`](../adr/ADR-0010-shot-detector-config-fields.md) |
| ADR-0011 | Hashed chromatic algorithm parameters are config fields | Accepted | [`ADR-0011`](../adr/ADR-0011-hashed-chromatic-parameters.md) |
| ADR-0012 | Chromatic compute uses OpenCV float Lab and sklearn MiniBatchKMeans | Accepted | [`ADR-0012`](../adr/ADR-0012-opencv-sklearn-chromatics.md) |

Phase 06 added two ADRs. Spatial thirds sigma, IoU tracking, primary-track weights, and `framing_rules_v1` are hashed `SpatialConfig` fields (ADR-0013); that change invalidates pre-Phase-06 default config hashes. The base spatial backends are `none` and `fake`; a real detector extra is not merged (ADR-0014).

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0013 | Hashed spatial algorithm parameters are config fields | Accepted | [`ADR-0013`](../adr/ADR-0013-hashed-spatial-parameters.md) |
| ADR-0014 | Base spatial backends are none and fake | Accepted | [`ADR-0014`](../adr/ADR-0014-spatial-backends-none-and-fake.md) |

Phase 07 added three ADRs. Farneback working resolution, discontinuity threshold, and nested flow hyperparameters are hashed `MotionConfig` fields (ADR-0015). Audio is FFmpeg mono s16le at the hashed sample rate and window; no LUFS library is added (ADR-0016). Tension hop, Gaussian cut kernel, robust-normalization percentiles, and epsilon are hashed `TensionConfig` fields; missing components renormalize and the language is tension proxy (ADR-0017). Those changes invalidate pre-Phase-07 default config hashes.

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0015 | Hashed motion algorithm parameters are config fields | Accepted | [`ADR-0015`](../adr/ADR-0015-hashed-motion-parameters.md) |
| ADR-0016 | FFmpeg PCM audio extraction without a LUFS library | Accepted | [`ADR-0016`](../adr/ADR-0016-ffmpeg-pcm-audio-no-lufs.md) |
| ADR-0017 | Hashed tension-proxy parameters and missing-component renormalization | Accepted | [`ADR-0017`](../adr/ADR-0017-hashed-tension-proxy-parameters.md) |

Phase 08 added two ADRs. Core tables change only through Alembic; the PostgreSQL
driver is `pg8000` so the base install stays Apache-2.0-distributable
(ADR-0018). FastAPI is a thin control plane; a separate local worker claims
queued rows and holds stage leases. The API does not import CV libraries
(ADR-0019).

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0018 | PostgreSQL schema is migrated with Alembic, never create_all | Accepted | [`ADR-0018`](../adr/ADR-0018-postgresql-schema-alembic.md) |
| ADR-0019 | Thin FastAPI control plane and a separate local worker | Accepted | [`ADR-0019`](../adr/ADR-0019-fastapi-control-plane-local-worker.md) |

Phase 09 added ADR-0020. Streamlit consumes HTTP only. Session state stores
identifiers. Timeline windows are bounded. Click-to-seek is one-way and
truncated to whole seconds. Streamlit/Plotly live in the `dashboard`
dependency group; the typed client uses httpx from the base install.

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0020 | Streamlit dashboard is an HTTP client with click-to-seek | Accepted | [`ADR-0020`](../adr/ADR-0020-streamlit-http-only-dashboard.md) |

Phase 10 added ADR-0021. Celery transports JSON `StageCommand` messages on
explicit CPU/GPU queues. Redis is not job truth. Celery/redis-py live in the
`celery` dependency group. The local poll worker remains the default profile.

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0021 | Celery JSON transport; PostgreSQL remains job truth | Accepted | [`ADR-0021`](../adr/ADR-0021-celery-json-redis-transport.md) |

Phase 11 added ADR-0022. Metrics and traces are in-process JSON. Cleanup is
limited to `tmp`/`quarantine` prefixes and resolved canonical keys. The API
enforces an in-flight analysis quota. Prometheus, OpenTelemetry, and psutil
are not added to the base install.

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0022 | In-process observability, bounded cleanup, and in-flight quotas | Accepted | [`ADR-0022`](../adr/ADR-0022-in-process-observability-and-quotas.md) |

Phase 12 added ADR-0023. The optional critic stays metrics-only. Adapters are
`none`, deterministic `fake`, and optional OpenAI-compatible HTTP via httpx.
Endpoints are settings, not hashed config. No Ollama or vLLM package.

| ID | Decision | Status | Record |
| --- | --- | --- | --- |
| ADR-0023 | Optional critic adapters: none, fake, OpenAI-compatible HTTP | Accepted | [`ADR-0023`](../adr/ADR-0023-optional-critic-adapters.md) |

ADR-0008 was added in Phase 00. The release model and first-party licence are a distinct irreversible decision from the detector gate in ADR-0007, and Phase 00 deliverable 4 requires a licence strategy, so it is recorded separately rather than folded into ADR-0007.

Phase 13 froze feature scope for candidate `0.1.0`. No new ADR. Current vs
future architecture is labelled in `docs/architecture/system-design.md`. The
optional critic remains ADR-0023. Compose/container verification is blocked on
hosts without Docker. Operator 60 s / 2160p clips remain absent; synthetic
CPU-core numbers are the published benchmark.

The deferred part of ADR-0007 is the only open decision from Phase 00: which of the three release paths in `docs/architecture/system-design.md` section 16 governs a real detector extra. Phase 06 completed with the fake backend; it still blocks publishing an AGPL-combined build. The 0.1.0 candidate does not include that extra.

## ADR template

```markdown
# ADR-NNNN: Short decision

- Status: Proposed | Accepted | Superseded
- Date: YYYY-MM-DD
- Owners: project owner
- Supersedes: optional ADR

## Context
What constraint or evidence forces a decision?

## Decision
What is chosen, precisely?

## Alternatives considered
What credible options were rejected and why?

## Consequences
What becomes easier, harder, or irreversible?

## Verification
What test, benchmark, or review will show the decision still works?

## Revisit trigger
What measurable event should reopen this decision?
```
