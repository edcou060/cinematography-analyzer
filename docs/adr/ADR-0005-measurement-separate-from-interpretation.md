# ADR-0005: Deterministic measurement is separated from optional interpretation

- Status: Accepted
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

The original concept made a local LLM critic a headline feature. That inverts the value: prose about a video is cheap and unfalsifiable, while reproducible measurement with traceable evidence is the hard part and the part worth showing.

A language model in the analysis path also destroys reproducibility. Sampling makes output non-deterministic, hosted models change under you, and a failed inference call would fail an analysis whose measurements had already succeeded. If prose can influence a stored metric, no metric can be defended.

`docs/architecture/system-design.md` section 3 (AD-05) fixes the layering. This ADR records the enforcement.

## Decision

Three layers, in a strict one-way dependency order.

1. **Measurement.** Deterministic code over pixels, audio samples, and container metadata. Every value declares a unit and a method version.
2. **Estimation.** Versioned, calibrated heuristics that turn measured features into labels such as a lighting-key estimate or a framing estimate. Each label carries a confidence, the evidence behind it, and the ability to abstain.
3. **Interpretation.** An optional language model that receives an already-validated report and emits short prose.

Interpretation output is stored in its own table, keyed to the analysis and to the report version it read. It is regenerable and deletable with no effect on any measurement. It is disabled by default (`critic.enabled: false`), and a critic failure or timeout is recorded against the critic alone: the analysis stays successful and the report is served without prose.

The critic never receives raw frames or audio, only the validated report. It cannot write to a measurement or estimation field; the data model gives it no such column, so this is a structural constraint rather than a convention.

## Alternatives considered

**Let the LLM produce structured metric values.** Rejected: unreproducible, unverifiable, and it would make every number in the report suspect.

**Let the LLM adjust confidence on heuristic labels.** Rejected. Superficially reasonable, and it would silently make interpretation an input to estimation, which is the exact inversion this ADR exists to prevent.

**Drop the critic entirely.** Rejected: bounded natural-language summary of validated metrics is genuinely useful, and building it as a strictly separate consumer demonstrates the layering. It stays optional.

**Run the critic before aggregation to enrich the report.** Rejected: it would place a non-deterministic step inside the reproducibility boundary that S3 depends on.

## Consequences

Easier: reproducibility (S3) holds regardless of critic behaviour. The critic can be swapped, re-prompted, re-run, or removed at any time. The demo works with no model server present.

Harder: an extra table, an extra cache key, and a second version axis, since prose must record which report version it described. Prose can go stale relative to a re-run analysis, so it is invalidated when the report version changes rather than silently kept.

## Verification

Two checks. Measured values are byte-identical with the critic enabled and disabled on the same input. Injecting a critic failure leaves the analysis successful and the report complete with interpretation absent. Both required by Phase 12.

## Revisit trigger

None that would allow a model to write a metric. If interpretation quality becomes a goal in itself, that is a new ADR about the critic's own evaluation, still downstream of measurement.
