# ADR-0011: Hashed chromatic algorithm parameters are config fields

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

`ChromaticConfig` already hashes `samples_per_shot`, `max_pixels_per_shot`, `clusters`, and `random_seed`. Lighting-key thresholds, letterbox cutoffs, MiniBatchKMeans `n_init`/`batch_size`, Delta-E merge distance, and working downscale were about to live as literals. A threshold change that is not part of the canonical config hash would reuse a previous analysis identity while producing different palettes or labels, which breaks S8.

Adding fields to a hashed model changes the default configuration digest. That is a cache-identity change and requires an ADR plus snapshot updates.

## Decision

`ChromaticConfig` gains hashed fields with defaults matching `docs/metrics/metric-definitions.md` section 4:

- `working_max_side`: longest downscale side in pixels before letterbox and sampling
- `kmeans_batch_size`, `kmeans_n_init`: MiniBatchKMeans constructor arguments
- `delta_e_merge`: CIE76 threshold for merging nearly identical Lab centres
- `letterbox_lstar_max`, `letterbox_coverage`, `min_usable_pixel_ratio`: border-connected near-black mask and abstain floor
- `shadow_lstar`, `highlight_lstar`: lightness histogram cutoffs
- `min_swatch_proportion`: drop unstable palette centres below this share after merge
- nested `lighting_key_rules`: versioned LOW/HIGH/BALANCED estimate thresholds

Schema version stays `1.0` because this is additive with defaults. `pipeline_version` stays `0.1.0`; existing cached identities from before this ADR cannot be reused against the new default hash, which is intended. Chromatic `method_version` is `chromatics-v1`.

Lighting-key values remain estimates. The continuous L* distribution is stored beside every label.

## Alternatives considered

**Keep thresholds in adapter literals keyed only by `method_version`.** Rejected: two configs that differ only in a lighting-key cutoff would share an analysis key.

**Nested free-form `params` dict.** Rejected: `extra="forbid"` contracts need named, typed fields.

## Consequences

Easier: changing a lighting-key or letterbox threshold invalidates identity; tests can inject rules without patching adapter internals.

Harder: default `AnalysisConfig` hash snapshots change once.

## Verification

`tests/contract/test_config_hash_snapshots.py` records the new default digest. A variant that only changes `lighting_key_rules.low_median_lstar` must hash differently.

## Revisit trigger

A calibrated lighting-key table replaces these starting thresholds; then bump `method_version` and, if the JSON shape changes, the config schema version.
