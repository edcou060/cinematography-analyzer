# ADR-0007: Gate the Ultralytics adapter out of the base installation

- Status: Accepted (the gate is decided; the choice among release paths is deliberately deferred)
- Date: 2026-09-05
- Owners: project owner
- Supersedes: none

## Context

Spatial analysis needs a person detector. YOLO11 via the `ultralytics` package is the obvious candidate: mature, accurate, easy to call.

Ultralytics publishes its licensing as two paths, AGPL-3.0 or a paid Enterprise licence (`https://www.ultralytics.com/license`, reference 4 in `docs/reference-sources.md`). AGPL-3.0's network-use provision reaches software offered to users over a network, which is precisely how this system is shaped: an HTTP API plus a browser dashboard. So the question is not merely whether the package can be imported for private experimentation, but what obligations attach if a combined work is distributed or offered as a service.

This project is released under Apache-2.0 (`docs/adr/ADR-0008-release-model-and-license.md`). Apache-2.0 and AGPL-3.0 are compatible in one direction only: Apache-2.0 code may be incorporated into an AGPL-3.0 work, and the combined work is then AGPL-3.0. A default installation that pulls in `ultralytics` would therefore make the shipped artifact's effective licence AGPL-3.0 while the repository advertises Apache-2.0. That contradiction must not be resolved silently by a line in a dependency file.

`docs/architecture/system-design.md` section 16 requires this choice to be made at release level. The phase guide permits the adapter to be gated rather than the licence to be chosen now.

## Decision

Two separable decisions, and only the first is settled.

**Decided — the gate.** Spatial detection sits behind a `SubjectDetector` protocol. The base installation, the default configuration, and the demo depend on no licensed detector. On a default install the spatial pillar reports `unavailable` with reason `detector_not_installed`, which is a supported product state described in `docs/product-contract.md`, not a failure.

The Ultralytics implementation lives in a separate optional installation extra, is never a base or transitive default dependency, and is selected only by explicit configuration. Installing that extra prints the AGPL-3.0 obligation and requires an explicit opt-in acknowledgement rather than assuming consent. Model weights are downloaded by the operator, never vendored in the repository, and their digest is recorded in provenance.

Two implementations ship in the base install: a deterministic fake detector for tests and golden fixtures, and the `unavailable` path. The vertical slice through Phase 05 is therefore complete with no detector at all.

**Deferred — which release path.** The three paths from section 16 remain open: relicense the compatible whole under AGPL-3.0; obtain an Enterprise licence; or implement a permissively licensed detector through the same port. This is recorded as a genuine blocking decision owned by the project owner and required before Phase 06 merges a real adapter or Phase 13 publishes a build including one. It blocks nothing before Phase 06.

## Alternatives considered

**Ultralytics as a base dependency.** Rejected: it makes the effective licence of the distributed artifact AGPL-3.0 by accident, and it puts a large model stack in the way of anyone who wants to run the chromatic slice.

**Relicense the project AGPL-3.0 now.** Rejected as premature, and it is the path that stays open longest, since Apache-2.0 can be absorbed into AGPL-3.0 later but not the reverse. Deciding now would trade an option away for nothing.

**Avoid person detection entirely.** Rejected: framing estimates and thirds proximity are core to the spatial pillar, and the port makes the detector replaceable rather than essential.

**Vendor the weights to make setup easier.** Rejected: the weights carry their own terms, and committing them would breach the rule against committing model artifacts.

**Rely on the package being permissive for private use.** Rejected as reasoning by hope. The gate costs one optional extra and removes the question.

## Consequences

Easier: the base install is small and permissively licensed. The vertical slice does not wait on CUDA, weights, or a licence decision. Swapping detectors is a configuration change, and the same port later accepts a permissive detector or SAM 2 without touching callers.

Harder: the default demo shows spatial analysis as `unavailable`, which must be presented as a deliberate release decision rather than an incomplete feature — the demo script does exactly that. The optional extra needs its own installation, configuration, and test path, and CI must prove the base install does not acquire the detector transitively.

Irreversible if got wrong: publishing one build that combines Apache-2.0 first-party code with AGPL-3.0 dependencies cannot be retracted from anyone who obtained it.

## Verification

A dependency test asserts that resolving the base installation from `uv.lock` yields no `ultralytics` node, from Phase 01. A behavioural test asserts that with no detector installed the analysis succeeds and the spatial pillar is `unavailable` with reason `detector_not_installed`, from Phase 06. The release checklist blocks publication of any artifact that bundles an AGPL-3.0 dependency under an Apache-2.0 declaration.

## Revisit trigger

Any of: the project owner selects one of the three release paths; Ultralytics changes its licensing terms; a permissively licensed detector of adequate accuracy becomes available, which would resolve this by making path 3 the obvious choice.
