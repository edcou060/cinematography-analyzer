# ADR-0014: Base spatial backends are none and fake

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

Phase 06 needs replaceable person detection so framing estimates and thirds proximity can be tested. ADR-0007 gates Ultralytics out of the base install and defers the section-16 release path (relicense AGPL-3.0, obtain Enterprise, or pick a permissive detector). Merging a real Ultralytics adapter before that choice would make the shipped extra's effective licence AGPL-3.0 while the repository advertises Apache-2.0.

The phase guide allows keeping only the port and a fake when the release posture is incompatible, and choosing that backend in an ADR.

## Decision

The base installation ships two spatial backends:

- `none` (default): the analysis succeeds; the spatial pillar is `UNAVAILABLE` with per-shot `NOT_COMPUTED` and reason `detector_not_installed`.
- `fake`: a deterministic detector for CI, contract tests, and `--spatial-backend fake`. It returns scripted boxes and, when no script is provided, a magenta-blob probe used by `composition_grid.mp4`.

No Ultralytics extra, PyTorch extra, or weight download is added in this phase. An unrecognised backend is treated like `none` (`detector_not_installed`), not as a failed analysis. Domain and application code do not import a detector SDK. SAM 2 remains excluded.

The deferred ADR-0007 release-path choice still blocks publishing a real detector extra or a build that bundles one. It no longer blocks completing the Phase 06 fake-driven slice.

## Alternatives considered

**Ship an opt-in Ultralytics extra now with an acknowledgement prompt.** Rejected: ADR-0007 says the owner must pick a section-16 path before Phase 06 merges a real adapter.

**Skip spatial until a permissive detector exists.** Rejected: the fake is enough to prove contracts, tracking, framing estimates, and overlays.

**Default the CLI to `fake`.** Rejected: the product contract requires a default install to report `detector_not_installed`.

## Consequences

Easier: CI stays CPU-only and Apache-2.0. Operators can still inspect geometry through the fake fixture.

Harder: the default report's spatial pillar is unavailable until a licensed or permissive detector is chosen.

## Verification

`tests/integration/spatial_fake` runs `--spatial-backend fake` on `composition_grid.mp4`. A default-backend test asserts `detector_not_installed`. `tests/unit/test_supply_chain.py` continues to forbid an `ultralytics` lockfile node.

## Revisit trigger

The project owner selects a section-16 path, or a permissively licensed detector of adequate accuracy becomes the obvious backend.
