# Phase 06 - Spatial composition baseline

## Mission

Add replaceable person detection/tracking and honest composition estimates. The report must remain valid without a person, without a GPU, or when the real detector is not legally/configurationally enabled.

## Context budget

Read only:

- `docs/project-state.md`
- detector licensing/model ADRs
- `docs/contracts/data-contracts.md` sections 7 and 10
- `docs/metrics/metric-definitions.md` section 5
- `docs/architecture/system-design.md` sections 6, 13, and 16
- current sampling/report ports and tests
- this phase guide

## Deliverables

- `SubjectDetector`, `SubjectTracker`, and `PrimarySubjectSelector` ports/services.
- Deterministic fake detector for all CI and contract tests.
- Optional real detector adapter behind an install extra and explicit license gate.
- Per-shot tracking reset, primary-track selection, thirds/center proximity, coverage, and framing estimate.
- Evidence overlay generator that draws boxes, centroids, thirds, and center guides.
- Calibration dataset/table and `framing_rules_v1` config.
- Spatial stage artifact and report integration with unavailable/no-subject states.

## Model decision

If using Ultralytics, keep the checkpoint configurable (`yolo11n.pt` may be the mature baseline; newer checkpoints are tested through the same adapter). Do not hardwire package result objects into domain code. Document AGPL/Enterprise implications before committing the adapter. If the release posture is incompatible, keep only the port/fake and choose a compatible backend in an ADR.

SAM 2 is explicitly excluded. Boxes are sufficient to validate pipeline boundaries. Add masks only after an evaluation demonstrates material benefit.

## Steps

1. Implement normalized detector output contracts and reject out-of-range/degenerate boxes.
2. Implement a fake that returns scripted observations for fixture sample IDs.
3. Select or implement a lightweight within-shot tracker. Reset at every shot boundary.
4. Implement deterministic primary-track scoring using coverage, area, and confidence; test ties.
5. Compute subject area/height ratios, centroids, track coverage, thirds proximity, and center proximity.
6. Create an annotated calibration table with clear visible definitions and `UNDETERMINED` cases.
7. Implement versioned framing rules from that table, plus a heuristic confidence based on coverage/agreement/margin.
8. Produce evidence overlays without altering source frames.
9. Return `NO_SUBJECT` when no stable candidate exists; do not invent zero-valued metrics.
10. Add the optional real adapter. Initialize model once per process and use inference mode.
11. Smoke-test on a tiny licensed fixture if hardware/backend is available. CI remains fake-driven.
12. Record model/package/weight digest/device/threshold in provenance.

## Required verification

```bash
uv run pytest tests/unit/spatial tests/contract/spatial tests/integration/spatial_fake -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run cine-analyzer analyze fixtures/video/composition_grid.mp4 --spatial-backend fake --output build/spatial-report.json
uv run cine-analyzer validate-report build/spatial-report.json
```

If the real adapter is enabled, run its marked smoke test separately and report hardware/model identity. Do not make the phase fail solely because optional GPU hardware is absent.

## Exit gate

- [ ] Domain/application layers do not depend on a detector SDK.
- [ ] No-person and unstable-track cases are valid, explicit results.
- [ ] Thirds is called proximity, not quality/compliance.
- [ ] Framing is an estimated/abstaining label backed by a calibration table.
- [ ] Evidence overlay makes geometry auditable.
- [ ] Real adapter licensing and weights identity are documented.
- [ ] `docs/project-state.md` points to Phase 07.
