# ADR-0004: Queue payloads carry references, never frame bytes

- Status: Accepted
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

The original concept had three consumers reading one shared-memory frame buffer, with the producer decoding the whole video concurrently from ingestion. On a single workstation this is attractive: decode once, fan out, no disk round trip.

It also couples every consumer to the producer's lifetime and buffer layout, requires a custom backpressure policy so the slowest consumer does not stall decode or overrun the ring, and offers no path to a second host. Worse, it invites the broker to become a frame transport, at which point a task message carries megabytes, retries re-send them, and the queue's memory becomes the pipeline's failure mode.

`docs/architecture/system-design.md` section 2 explains why the shared-memory fan-out is not the baseline, and section 3 (AD-03) fixes reference-only messages.

## Decision

Cross-process messages contain only identifiers and small JSON metadata: `video_id`, `analysis_id`, `shot_id`, time ranges in integer milliseconds, `config_hash`, `pipeline_version`, and artifact URIs. A message body has a small bounded size; the working budget is a few kilobytes.

Never serialized through a queue: decoded frames, NumPy arrays, OpenCV `Mat` objects, PyTorch tensors or model objects, audio buffers, complete reports, or pickled domain objects.

Producers write immutable artifacts and publish their identifiers. Consumers read exactly the artifacts they need, directly from the artifact store. The sampling plan itself is a versioned artifact, so what a downstream stage will read is decided once, deterministically, and is inspectable after the fact.

Shared memory remains a legitimate single-host optimization, but only behind a `FrameStore` port whose public contract is identical to the artifact-backed implementation. Adopting it must not change any stage's signature.

## Alternatives considered

**Shared-memory ring buffer as the baseline.** Rejected as the baseline for the coupling, backpressure, and lifecycle reasons above. Retained as a measured optimization behind a port.

**Frame bytes in the queue message.** Rejected: broker memory pressure, expensive redelivery, and a hard size ceiling.

**Decode the full video once into per-frame files.** Rejected: an unbounded artifact set for a metric suite that samples a few frames per shot. The sampling plan exists precisely so that only necessary frames are materialized.

**Each consumer decodes the source independently.** Rejected: duplicated decode cost and, with variable frame rate, a real risk of two stages disagreeing about which frame a timestamp names. One sampling plan removes that ambiguity.

## Consequences

Easier: a worker can move to another host with no protocol change. Retries are cheap and idempotent. A failed analysis can be re-run from its stored plan. Stage inputs are inspectable, so a disputed metric can be traced to the exact artifact it read.

Harder: an artifact store, a naming scheme, atomic writes, and a retention policy are required from Phase 03. Frames are re-read from disk rather than found in memory, which costs I/O the shared-memory design would have avoided.

Cost accepted knowingly: this trades single-host speed for a contract that survives distribution. If profiling later shows artifact I/O dominates, the `FrameStore` port is where that is fixed.

## Verification

A test asserts that every task payload serializes to JSON under the size budget and that no payload field holds a binary or array type. Message shapes are validated by strict Pydantic models with `extra="forbid"`, from Phase 02.

## Revisit trigger

Profiling shows artifact read and write exceeds 30 % of wall time on `bench-03-lowlight-handheld`. The response is a shared-memory `FrameStore` implementation behind the existing port, not frames in the queue.
