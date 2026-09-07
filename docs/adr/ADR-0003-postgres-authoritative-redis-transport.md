# ADR-0003: PostgreSQL is authoritative state; Redis is transport only

- Status: Accepted
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

A job pipeline needs somewhere to record what has happened. Redis is present anyway as a broker, is fast, and is tempting: keeping progress there avoids a schema and a migration.

It is also the wrong place. Redis default persistence can lose recent writes on an unclean stop, it has no transactional compare-and-set across several related rows, and it has no foreign keys to stop an analysis from referring to a video that does not exist. Success criterion S2 in `docs/product-contract.md` requires that job state survive a worker or UI restart, which rules out a store that may lose the last few seconds of writes.

## Decision

PostgreSQL is the single authoritative record of videos, analyses, stage states, and report metadata. Every state transition is a transactional compare-and-set against the expected prior state, so a redelivered task cannot move a job backwards or double-apply a transition.

Redis carries task messages, ephemeral caches, and rate-limit counters. Losing the entire Redis instance must cost at most in-flight task delivery and warm caches. It must never lose the answer to "what is the state of this analysis". Recovery from that loss is re-enqueueing work that PostgreSQL already describes.

The API reads status from PostgreSQL. Workers write state to PostgreSQL. Neither treats a Redis value as the truth about a job.

## Alternatives considered

**Redis as the primary job store.** Rejected: no cross-row transactions, no referential integrity, and a durability model that contradicts S2.

**Celery result backend as job state.** Rejected: it records task outcomes, not the domain state machine. Its retention is a cache policy, and it has no vocabulary for a stage that finished with a pillar `unavailable`.

**SQLite for the MVP, PostgreSQL later.** Rejected: writer concurrency and type differences would make the Phase 10 migration a rewrite of exactly the concurrency behaviour that matters most. One database engine from the start.

**Event log as the source of truth.** Rejected as premature: correct, and heavier than a single-user analysis tool needs. A state table with transactional transitions is sufficient and far easier to inspect.

## Consequences

Easier: restart safety, inspectable state with plain SQL, and referential integrity that makes orphaned artifacts detectable rather than invisible.

Harder: a schema and migrations exist from Phase 02, and PostgreSQL must be running for tests that touch persistence. Status polling hits a database rather than an in-memory value, so the status endpoint needs an index and a bounded query.

Irreversible in practice: the persistence tables become a public contract under `docs/contracts/data-contracts.md`, changeable only by migration.

## Verification

A restart test: kill the worker mid-analysis, restart it, and confirm the analysis resumes or reports failure with no state lost and no duplicated transition. A Redis-loss test: flush Redis mid-analysis and confirm job state is still fully readable from PostgreSQL. Both introduced by Phase 10 and required for release.

## Revisit trigger

Status-read load makes PostgreSQL the measured bottleneck. The response is a read-through cache in front of it, not a change of the system of record — which would need a new ADR arguing against S2.
