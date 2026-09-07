# Phase 07 - Motion, audio, and tension components

## Mission

Add time-aligned motion and audio measurements, then combine observable normalized components into an explainable tension proxy. Never claim to measure audience emotion.

## Context budget

Read only:

- `docs/project-state.md`
- motion/audio/tension ADRs
- `docs/contracts/data-contracts.md` section 8
- `docs/metrics/metric-definitions.md` sections 2, 6-8
- `docs/operations/quality-and-operations.md` sections 2-4
- current sampling/report code and tests
- this phase guide

## Deliverables

- Motion analyzer with global/residual summaries and valid-flow quality.
- Audio extractor and window feature analyzer; valid no-audio result.
- Timeline alignment/resampling service.
- Cut, audio, and motion component normalization.
- Configurable tension proxy with missing-component weight renormalization.
- Timeline artifact and report reference.
- Synthetic signal/video golden fixtures.

## Steps

1. Finalize motion sample FPS/resolution and add it to the deterministic sampling plan.
2. Compute flow only within shot boundaries; reject/flag pairs with cut-like discontinuity.
3. Estimate robust global background motion and residual motion. Exclude subject regions when available but operate without them.
4. Normalize magnitude by frame diagonal and elapsed time; report median, p90, valid ratio, and direction consistency.
5. Extract audio through FFmpeg to a controlled mono sample rate with timeout and output limit.
6. Implement RMS/dBFS, onset strength, and spectral flux; add short-term LUFS only with an explicitly chosen/tested library.
7. Represent no audio as `NO_AUDIO`, not silence and not failure.
8. Align features to integer-millisecond timeline windows. Unit-test offsets and last partial window.
9. Robust-normalize components using documented percentiles/epsilon behavior. Constant signals must produce a stable defined result.
10. Build local cut activity and combine components with versioned weights.
11. Renormalize weights when a component is unavailable and emit a warning.
12. Store every component; never persist only the combined curve.
13. Add synthetic impulses, ramps, silence, moving object, translated background, and cut-boundary tests.

## Required verification

```bash
uv run pytest tests/unit/motion tests/unit/audio tests/unit/timeline tests/golden/temporal_audio -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run cine-analyzer analyze fixtures/video/tension_signals.mp4 --output build/tension-report.json
uv run cine-analyzer inspect-timeline build/tension-report.json
```

Inspect peaks against known synthetic events. Verify all values are finite, bounded, monotonic with isolated component changes, and time-aligned.

## Exit gate

- [ ] Flow never crosses shot boundaries.
- [ ] Global and residual motion are separate.
- [ ] Audio units and window/hop are explicit.
- [ ] No-audio is a valid result.
- [ ] Each tension component is stored and visible.
- [ ] Missing components renormalize deterministically.
- [ ] UI/report language says tension proxy.
- [ ] `docs/project-state.md` points to Phase 08.
