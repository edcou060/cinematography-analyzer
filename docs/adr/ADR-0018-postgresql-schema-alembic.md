# ADR-0018: PostgreSQL schema is migrated with Alembic, never create_all

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

Phase 08 promotes job state out of disposable SQLite into PostgreSQL (ADR-0003).
The tables become a public contract: unique video hashes, unique analysis keys,
stage leases, and terminal-state guards. Calling `metadata.create_all()` at
startup would hide migration drift and cannot express partial unique indexes.

The base-install licence gate (ADR-0008) also constrains the driver. `psycopg`
and `psycopg2` are LGPL, which this repository's lockfile check does not treat
as Apache-2.0-distributable. A permissive, SQLAlchemy-supported driver is
required.

## Decision

Authoritative control-plane tables live in PostgreSQL and change only through
Alembic. Runtime code never calls `create_all()`. The CLI Profile A path may
keep disposable SQLite for `cine-analyzer analyze`; the API and local worker
use PostgreSQL only.

The initial schema is:

- `videos` — unique `content_sha256`, JSON metadata, storage keys
- `analyses` — unique `analysis_key`, unique
  `(video_id, configuration_hash, pipeline_version)`, hashed config snapshot,
  overall state, progress in `[0, 1]`, optional failure summary
- `stage_runs` — unique `(analysis_id, stage_name, attempt)`, lease token and
  expiry, compare-and-set completion; unique successful row per
  `(analysis_id, stage_name)` via a partial unique index
- `shots` — unique `(analysis_id, shot_index)`, `end_ms > start_ms`
- `artifacts` — unique `storage_key`, checksum, media type
- `report_summaries` — one row per finished analysis, availability JSON
- `critique_runs` — reserved for Phase 12; unused by this phase's application code

The SQLAlchemy 2 driver is `pg8000` (`postgresql+pg8000://`). Domain and
application modules do not import SQLAlchemy or Alembic.

Local worker stages for this phase are `sampling`, `report`, and `aggregate`.
Each wraps existing pipeline entry points. Per-pillar Celery tasks remain
Phase 10.

## Alternatives considered

**SQLAlchemy `create_all()` for local bootstrap.** Rejected: it cannot apply
partial indexes or remain the production migration strategy.

**psycopg3 as the driver.** Rejected for the base install: LGPL metadata would
fail the lockfile licence gate. Revisit if the project explicitly reviews LGPL
linking.

**One leased stage for the whole pipeline.** Rejected: lease races, stale
completion, and retry attempts would be untestable as specified.

## Consequences

Easier: inspectable SQL, restart-safe jobs, and a single migration history.

Harder: API/worker tests need a running PostgreSQL. The CLI SQLite schema is
not a migration path and must not grow control-plane tables.

## Verification

`uv run alembic upgrade head` against an empty database succeeds.
`tests/integration/postgres` prove duplicate analysis creation, two stage
claimants, stale completion, and retry attempts.

## Revisit trigger

A second database engine is required, or the driver licence review accepts
psycopg; then bump this ADR rather than silently switching dialects.
