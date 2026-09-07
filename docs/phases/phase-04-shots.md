# Phase 04 - Shot detection and sampling manifest

## Mission

Produce a validated `ShotSet`, deterministic `SamplingPlan`, and extracted evidence frames for a local analysis. This is the first sequential decode stage.

## Context budget

Read only:

- `AGENTS.md`
- `docs/project-state.md`
- shot/sampling ADRs
- `docs/architecture/system-design.md` sections 7-9
- `docs/contracts/data-contracts.md` sections 4-5
- `docs/metrics/metric-definitions.md` sections 2-3
- relevant Phase 03 ports/adapters/tests
- this phase guide

## Deliverables

- `ShotDetector` and `SampleExtractor` protocols.
- Pinned PySceneDetect adapter; translate third-party “scene” names to domain shots.
- Deterministic sample planner supporting chromatic/composition/motion/evidence purposes.
- Ordered extraction adapter using PyAV or FFmpeg, selected and documented by ADR.
- Shot and sampling artifacts with evidence checksums/timestamps.
- Golden cut/fade/flash/no-cut fixtures and evaluation report.
- CLI output listing shots and evidence paths/IDs.

## Steps

1. Add the minimal media dependencies and lock them. Pin PySceneDetect below the next major API boundary.
2. Implement detector adapter configuration without hardcoding a magic threshold in application code.
3. Detect the full supported clip in presentation order at a documented working resolution.
4. Add start/end outer boundaries and validate complete, contiguous, non-overlapping coverage.
5. Define behavior for no detected internal boundary and sub-minimum shots.
6. Build sample targets per purpose. Deduplicate identical timestamps while preserving all purpose tags.
7. Extract targets in ascending timestamp order and record requested vs actual decoded timestamp.
8. Reject cross-shot substitutions; return explicit unavailable sample status.
9. Store representative frames and the sampling manifest atomically.
10. Evaluate boundary precision/recall within a documented tolerance on golden fixtures. Save detector configuration and per-frame stats in debug mode.

## Required verification

```bash
uv run pytest tests/unit/shots tests/unit/sampling tests/integration/shots tests/golden/shots -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run cine-analyzer analyze fixtures/video/two_color_cut.mp4 --through sampling
```

Inspect the generated manifest and representative images. Tests must assert exact interval coverage, deterministic target IDs/order, and correct hard-cut timing within tolerance.

## Exit gate

- [ ] The system consistently calls outputs shots, not narrative scenes.
- [ ] No-boundary video returns one valid shot.
- [ ] Shot intervals cover the video exactly within the documented duration/timestamp policy.
- [ ] Sampling is deterministic and purpose-aware.
- [ ] Requested/decoded timestamps are both preserved.
- [ ] Evidence artifacts are atomic and checksummed.
- [ ] Golden detector results are recorded.
- [ ] `docs/project-state.md` points to Phase 05.

## Cursor prompt

```text
Execute Phase 04 from docs/phases/phase-04-shots.md. Implement pinned shot
detection, validated shot intervals, deterministic multi-purpose sampling, and
ordered evidence extraction. Do not implement chromatics, spatial inference,
audio, web API, or queues. Prove timing/coverage with golden media fixtures,
inspect artifacts, update docs/project-state.md, and stop.
```
