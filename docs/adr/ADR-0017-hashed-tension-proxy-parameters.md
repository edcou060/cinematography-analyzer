# ADR-0017: Hashed tension-proxy parameters and missing-component renormalization

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

The tension number is a configurable **tension proxy**, not audience emotion. Kernel
width, reference density, robust-normalization percentiles, epsilon, and timeline hop
change the curve. If they live only as adapter literals, two configs could share an
analysis identity while producing different combined values.

Missing audio must not be stored as silence. Remaining weights must still sum to one.

## Decision

`TensionConfig` keeps hashed `weights` (defaults 0.35 / 0.30 / 0.35) and gains:

- `hop_ms`: 500 (timeline window start; last partial window is emitted)
- `cut_sigma_ms`: 750 (Gaussian kernel on internal shot boundaries)
- `cut_reference`: 3.0
- `percentile_low` / `percentile_high`: 10 / 90
- `epsilon`: 1e-6

`N(x)=clip((x-p10)/(p90-p10+ε), 0, 1)`. A constant series is defined: the denominator
becomes ε and every value is 0.

When a component is unavailable, its configured weight is set to 0, remaining weights
are renormalized to sum to 1, and a warning is stored (`audio_unavailable_weights_renormalized`
and/or `motion_unavailable_weights_renormalized`). All three component curves are stored
on every timeline point; the combined curve is never persisted alone. Language on the
CLI and timeline summary is **tension proxy**.

`A(t)` is the mean of robust-normalized onset, spectral flux, and linear RMS recovered
from dBFS. `M(t)` is the mean of robust-normalized global and residual motion. Those mix
rules are part of `tension-v1`; changing them requires a method bump.

`Timeline` gains additive `hop_ms`, `window_ms`, `weights`, `effective_weights`,
`warnings`, and `method_version` with defaults so older documents still parse.

Schema version stays `1.0`. `pipeline_version` stays `0.1.0`.

## Alternatives considered

**Drop unavailable components from storage.** Rejected: users must see why the proxy
moved; zeros plus a warning are not the same as omitting the series.

**Call the field a tension index.** Rejected: product language requires proxy, not
emotion or artistic truth.

## Consequences

Easier: hop, kernel, and normalization are part of identity; no-audio degradation is
deterministic.

Harder: default config hash snapshots change (with ADR-0015 and ADR-0016).

## Verification

Unit tests: last partial window, constant-signal normalization, isolated-component
monotonicity, renormalization. Golden `tension_signals.mp4` peaks near the known cut,
beeps, and motion events. `inspect-timeline` prints **tension proxy** and all three
components.

## Revisit trigger

A calibrated cross-video reference distribution replaces within-clip percentiles, or
smoothing of aligned components is persisted; then bump `tension-v1`.
