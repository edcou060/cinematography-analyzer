# ADR-0015: Hashed motion algorithm parameters are config fields

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

`MotionConfig` already hashes `sample_fps`. Farneback working resolution, discontinuity
flagging, and the dense-flow hyperparameters were about to live as adapter literals. A
threshold change that is not part of the canonical config hash would reuse a previous
analysis identity while producing different global or residual magnitudes, which breaks
S8.

Adding fields to a hashed model changes the default configuration digest. That is a
cache-identity change and requires an ADR plus snapshot updates.

## Decision

`MotionConfig` gains hashed fields with defaults matching `docs/metrics/metric-definitions.md`
section 6.2:

- `working_max_side`: 320 (longest side after aspect-preserving downscale)
- `discontinuity_diag_per_s`: 1.5 (flag a pair when global magnitude exceeds this many
  frame-diagonals per second)
- nested `farneback`: `pyr_scale` 0.5, `levels` 3, `winsize` 15, `iterations` 3,
  `poly_n` 5, `poly_sigma` 1.2

Schema version stays `1.0` because this is additive with defaults. `pipeline_version`
stays `0.1.0`; existing cached identities from before this ADR cannot be reused against
the new default hash, which is intended. Motion `method_version` is `motion-v1`.

Flow is computed only between adjacent motion samples that share a shot. Global and
residual magnitudes are separate. Camera-movement labels (pan, tilt, zoom, handheld)
are not configured or emitted.

`TemporalValue` gains optional `motion_magnitude_p90`, `flow_valid_ratio`, and
`direction_consistency` with default `None` so older documents still parse.

## Alternatives considered

**Keep Farneback parameters in adapter literals keyed only by `method_version`.**
Rejected: two configs that differ only in working resolution would share an analysis
key.

**Emit camera-movement labels from global-flow direction.** Rejected: the phase forbids
presenting those guesses as fact; they remain a stretch feature.

## Consequences

Easier: changing a Farneback window or discontinuity threshold invalidates identity;
tests inject parameters without patching internals.

Harder: default `AnalysisConfig` hash snapshots change once (together with ADR-0016 and
ADR-0017).

## Verification

`tests/contract/test_config_hash_snapshots.py` records the new default digest. A variant
that only changes `motion.working_max_side` must hash differently. Unit tests assert
that a pair spanning two shots is never formed.

## Revisit trigger

An affine/homography global model replaces the median vector, or camera-movement labels
are added with a calibration set; then bump `motion-v1`.
