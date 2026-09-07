# ADR-0006: Integer milliseconds at every persisted and transported boundary

- Status: Accepted
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

Video time arrives in several incompatible shapes: rational frame rates such as 30000/1001, presentation timestamps in a stream time base, floating-point seconds from detector libraries, and human timecode strings. Mixing them produces bugs that are individually tiny and collectively unfixable — a shot list whose durations do not sum to the clip length, two stages disagreeing about which frame a timestamp names, and equality comparisons that fail on values that print identically.

Floating-point seconds are the specific hazard. `0.1 + 0.2 != 0.3`, accumulated addition drifts, and a value used as a cache or dedup key that differs in its last bit produces a spurious miss. Success criterion S3 requires byte-identical measured values across runs, which a float time axis cannot supply reliably.

## Decision

Integer milliseconds are the canonical unit for every duration and instant that is persisted, transported, hashed, or compared. Column types are integers; Pydantic fields are `int`; queue payload time ranges are integers.

Conversion happens exactly twice. Once inbound: presentation timestamps and stream time bases are converted to integer milliseconds at the ingestion boundary, with a single documented rounding rule applied consistently rather than per call site. Once outbound: milliseconds become seconds or timecode at the presentation boundary only, in formatting code, and the converted value is never fed back into a computation.

Frame indices are kept alongside millisecond values rather than derived from them, because a millisecond value cannot round-trip to a frame index under a variable frame rate. Evidence references carry both.

Sub-millisecond precision is not represented. At 60 fps a frame is about 16.7 ms, so millisecond resolution is roughly seventeen times finer than a frame — well inside the noise of shot-boundary detection.

## Alternatives considered

**Float seconds.** Rejected: drift, unstable equality, and unusable as a hash or dedup key.

**Rational time base preserved throughout, as FFmpeg does.** Rejected as disproportionate. It is the most correct option and it makes every arithmetic operation, comparison, database column, and JSON field more complex, to gain precision below one frame that no metric in this product uses.

**Nanoseconds or microseconds as integers.** Rejected: correct and needlessly wide. Milliseconds already exceed frame resolution, and they read naturally in stored JSON.

**Frame indices only.** Rejected: not comparable across clips with different frame rates, and meaningless for audio-derived metrics.

## Consequences

Easier: exact equality, safe summation, stable hashing, sortable integer columns, and durations that reconcile against clip length exactly.

Harder: every field name must state its unit, so the convention is an explicit `_ms` suffix. Reviewers reading a stored report see `2_003` rather than `2.003`, which is a presentation-layer concern.

Irreversible in practice: the unit is baked into column types and public schemas. Changing it means a major schema version and a migration.

## Verification

Two checks from Phase 02. A schema test asserts that every time-typed field in a persisted or transported model is an integer and carries the `_ms` suffix. A reconciliation test asserts that shot durations sum to the probed clip duration within one millisecond per shot boundary, on both constant and variable frame-rate fixtures.

## Revisit trigger

A required metric needs sub-millisecond precision — for example frame-accurate audio-to-video offset measurement below one millisecond. That would need a new ADR proposing a rational or microsecond time base together with a migration plan.
