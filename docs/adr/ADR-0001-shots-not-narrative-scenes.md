# ADR-0001: Call detected edit intervals shots, not scenes

- Status: Accepted
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

PySceneDetect names its output "scenes". The name is a library convention, not a semantic claim: the detector compares adjacent frames and reports where a threshold was crossed. It has no access to dialogue, location, or dramatic structure.

The original concept adopted the library's word. Carrying it into the domain model would promise semantic grouping that the MVP does not perform, and it would consume the only good name for a real future feature. `docs/architecture/system-design.md` section 3 (AD-01) already fixes the corrected terminology; this ADR records the decision and its cost.

## Decision

The domain types are `Shot` and `ShotBoundary`. A shot boundary is a detected visual transition. A shot is the half-open interval between two consecutive boundaries.

The identifier `scene` is reserved. It does not appear in domain types, database columns, API fields, artifact schemas, configuration keys, or user-facing copy for any detector output. The phrase "narrative scene" is used only to name the thing the MVP does not do.

Where the detector library's own API says "scene", the adapter renames at the boundary, in one place, so the library's vocabulary never leaks past the adapter.

## Alternatives considered

**Keep the library's `scene`.** Rejected: cheapest to write, most expensive to correct. Renaming a persisted field later means a schema major version and a data migration, and until then every reviewer has to be told that the field does not mean what it says.

**Use a neutral word such as `segment` or `interval`.** Rejected: accurate but discards the correct film-language term. "Shot" is what the industry calls the interval between two edits, and using it makes the report legible to the people it is for.

**Say `shot` in the interface and `scene` in the code.** Rejected: a translation layer with no benefit, and the two vocabularies drift apart the moment anyone adds a field.

## Consequences

Easier: a future narrative-grouping feature can introduce `NarrativeScene` with no rename, no migration, and no ambiguity. Reports read correctly to a filmmaker.

Harder: every detector adapter must translate at its boundary, and reviewers arriving from PySceneDetect's documentation need one sentence of orientation.

Irreversible in practice: once `shot` is persisted and served, renaming it costs a major schema version. That is the intended direction of the ratchet.

## Verification

A repository-wide search finds no `scene` identifier in `src/`, migrations, schemas, or dashboard copy outside an explicit narrative-scene disclaimer and the detector adapter's internal translation. Enforced by a documented check from Phase 02 onward and re-run at Phase 13.

## Revisit trigger

A narrative-grouping feature is specified and accepted. At that point a new ADR defines `NarrativeScene` as a grouping over shots; it does not reopen this one, because the two names can coexist.
