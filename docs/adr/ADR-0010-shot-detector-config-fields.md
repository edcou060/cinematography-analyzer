# ADR-0010: Hashed shot-detector parameters are config fields

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

`ShotsConfig` already hashes `backend`, `detector`, and `min_shot_ms`. Detector working resolution and thresholds were about to live as literals in application code. A threshold change that is not part of the canonical config hash would reuse a previous analysis identity while producing different shots, which breaks S8.

Adding fields to a hashed model changes the default configuration digest. That is a cache-identity change and requires an ADR plus snapshot updates.

## Decision

`ShotsConfig` gains hashed fields:

- `working_width`: target decode width in pixels for detection (height follows aspect ratio)
- `threshold`: detector threshold (`adaptive_threshold` or content threshold, depending on `detector`)
- `min_content_val`: AdaptiveDetector minimum content value; ignored by `content`
- `debug`: when true, persist per-frame detector stats as a stage artifact

Defaults match PySceneDetect 0.6/0.7 AdaptiveDetector (`threshold=3.0`, `min_content_val=15.0`) and a 320-pixel working width. Schema version stays `1.0` because this is additive with defaults. `pipeline_version` stays `0.1.0`; existing cached identities from before this ADR cannot be reused against the new default hash, which is intended.

## Alternatives considered

**Keep thresholds in adapter literals keyed only by `method_version`.** Rejected: two configs that differ only in threshold would share an analysis key.

**Nested free-form `params` dict.** Rejected: `extra="forbid"` contracts need named, typed fields.

## Consequences

Easier: changing a threshold invalidates identity; tests can inject a detector config without patching adapter internals.

Harder: default `AnalysisConfig` hash snapshots change once.

## Verification

`tests/contract/test_config_hash_snapshots.py` records the new default digest. A variant that only changes `threshold` must hash differently.

## Revisit trigger

PySceneDetect 0.8 (or a detector backend change) introduces incompatible parameter names; then bump `method_version` and, if the JSON shape changes, the config schema version.
