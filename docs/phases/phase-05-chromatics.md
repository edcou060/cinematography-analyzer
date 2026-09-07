# Phase 05 - Chromatic vertical slice

## Mission

Complete the first useful end-to-end analysis: video -> shots -> sampled frames -> per-shot palette/lightness/lighting estimate -> local report JSON. This phase proves the architecture without a GPU.

## Context budget

Read only:

- `AGENTS.md`
- `docs/project-state.md`
- chromatic/config/schema ADRs
- `docs/contracts/data-contracts.md` sections 3, 6, 9, and 12
- `docs/metrics/metric-definitions.md` sections 1, 4, 9, and 10
- relevant sampling/artifact code and tests
- this phase guide

## Deliverables

- Pure chromatic feature functions and a `ChromaticAnalyzer` application port.
- OpenCV/scikit-learn adapter using float CIE Lab and deterministic `MiniBatchKMeans`.
- Letterbox detection/mask with quality ratio.
- Per-shot chromatic stage artifact and method provenance.
- Minimal report aggregator for temporal shot summary + chromatics.
- CLI command producing validated report JSON.
- Golden palette/lightness fixtures and visual evidence review script/page.

## Steps

1. Add only NumPy, OpenCV headless, scikit-learn, and necessary color dependency. Lock and record versions.
2. Normalize rotation/color input and sample pixels deterministically. Do not concatenate frames as spatial images.
3. Implement border-connected letterbox masking; return usable-pixel ratio and abstain if too little remains.
4. Convert uint8 RGB -> float `[0,1]` -> Lab; unit-test black/white/known colors and L-star range.
5. Fit MiniBatchKMeans with explicit cluster count, seed, batch size, and `n_init`.
6. Count membership, sort by prevalence, convert centers to RGB/uppercase hex, and merge/handle duplicate centers deterministically.
7. Compute L-star percentiles, spread, shadow/highlight ratios, and clipping proxies.
8. Implement the versioned lighting-key rules from configuration. Label them estimates.
9. Store evidence sample IDs and provenance with each measurement.
10. Aggregate a valid local `AnalysisReport`; absent stages use explicit `NOT_COMPUTED` measurements.
11. Add golden frames: solid colors, 80/20 mixture, grayscale gradient, letterboxed color, and fewer-than-five-color input.
12. Run twice and compare canonical numeric/ordering output within documented tolerance.

## Required verification

```bash
uv run pytest tests/unit/chromatic tests/contract tests/golden/chromatic tests/integration/report -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run cine-analyzer analyze fixtures/video/two_color_cut.mp4 --output build/report.json
uv run cine-analyzer validate-report build/report.json
```

Manually inspect palette swatches/evidence for every golden frame. Confirm black bars do not dominate the letterboxed example.

## Exit gate

- [ ] Float Lab ranges and L-star units are proven by tests.
- [ ] Palette order reflects prevalence and is deterministic.
- [ ] Letterbox masking reports quality and abstains safely.
- [ ] Lighting labels are versioned estimates with visible continuous evidence.
- [ ] Local report validates against the public schema.
- [ ] Same input/config/version produces equivalent output.
- [ ] `docs/project-state.md` points to Phase 06.

## Cursor prompt

```text
Execute Phase 05 from docs/phases/phase-05-chromatics.md. Complete the CPU-only
vertical slice through a validated report: deterministic pixel sampling, float
CIELAB, prevalence-sorted palette, lightness features, versioned lighting-key
estimate, evidence, and golden tests. Do not add spatial models, audio, FastAPI,
Celery, or Streamlit. Run/inspect the outputs, update project state, and stop.
```
