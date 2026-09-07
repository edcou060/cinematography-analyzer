# ADR-0013: Hashed spatial algorithm parameters are config fields

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

`SpatialConfig` already hashes `backend`, `checkpoint`, `sample_fps`, and `person_confidence`. Thirds sigma, IoU tracking, primary-track weights, and `framing_rules_v1` height thresholds were about to live as adapter literals. A threshold change that is not part of the canonical config hash would reuse a previous analysis identity while producing different framing estimates or proximity scores, which breaks S8.

Adding fields to a hashed model changes the default configuration digest. That is a cache-identity change and requires an ADR plus snapshot updates.

## Decision

`SpatialConfig` gains hashed fields with defaults matching `docs/metrics/metric-definitions.md` section 5 and `docs/metrics/framing_calibration_v1.md`:

- `thirds_sigma`: Gaussian width for thirds and center proximity
- `track_iou_min`: within-shot association floor
- nested `primary_track_weights`: coverage / median area / median confidence, summing to one
- nested `framing_rules`: version string `framing_rules_v1` plus ordered person-height thresholds, track-coverage floor, edge truncation, and disagreement fraction

Schema version stays `1.0` because this is additive with defaults. `pipeline_version` stays `0.1.0`; existing cached identities from before this ADR cannot be reused against the new default hash, which is intended. Spatial `method_version` is `spatial-v1`.

Framing labels remain estimates. Thirds proximity is geometric proximity, not composition quality. Overlay drawing is evidence, not a hashed measurement input.

## Alternatives considered

**Keep thresholds in adapter literals keyed only by `method_version`.** Rejected: two configs that differ only in a height cutoff would share an analysis key.

**Hash overlay rendering flags.** Rejected: overlays do not change `SpatialValue`.

## Consequences

Easier: changing a framing cutoff or thirds sigma invalidates identity; tests inject rules without patching internals.

Harder: default `AnalysisConfig` hash snapshots change once.

## Verification

`tests/contract/test_config_hash_snapshots.py` records the new default digest. A variant that only changes `framing_rules.medium_height_max` must hash differently.

## Revisit trigger

A calibrated table replaces these starting thresholds, or a face-height signal is added; then bump `framing_rules` version and `spatial-v1`.
