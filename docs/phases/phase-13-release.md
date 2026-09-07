# Phase 13 - Benchmark, documentation, demo, and release

## Mission

Turn the tested system into a credible portfolio centerpiece. Freeze scope, reproduce deployment, publish evidence, and demonstrate both success and controlled failure.

## Context budget

Read only:

- `AGENTS.md`
- `docs/project-state.md`
- accepted ADR index
- `docs/architecture/system-design.md` sections 1, 5, 18, and 19
- `docs/operations/quality-and-operations.md` sections 12-17
- latest benchmark/report schemas and README
- this phase guide

## Deliverables

- Release-candidate tag/version and clean lock/container builds.
- Final README with architecture, quickstart, evidence screenshots, benchmark table, tradeoffs, and limitations.
- `docs/demo-script.md` for a 3-5 minute portfolio demonstration.
- Reproducible benchmark report with hardware/input/config/commit.
- Architecture and report examples matching actual deployment.
- API schema, sample validated report, and sanitized screenshots.
- Third-party notices, SBOM/security scan summary, and release checklist.
- Backlog organized by measured revisit triggers, not hype.

## Demo narrative

1. State the engineering problem and honest limits in 20 seconds.
2. Upload a legally shareable 30-60 second clip.
3. Show durable async stages and resource separation.
4. Inspect one shot: evidence, palette, lightness, composition, and provenance.
5. Show editing distribution and tension components.
6. Trigger or show a pre-recorded optional-stage failure and the valid partial report.
7. Show one profiling flame graph/table and the measured optimization.
8. Close with architecture tradeoffs and next measured trigger.

## Steps

1. Freeze dependencies/config defaults and rerun clean-clone bootstrap.
2. Run all checks and database migrations in release mode.
3. Execute benchmark corpus cold/warm; create comparison table and machine-readable artifact.
4. Verify screenshots/text against current terminology and stage availability.
5. Generate a small sample report from redistributable fixture; remove local paths/IDs as needed without falsifying schema.
6. Verify diagrams match deployed components. Remove future components from current-state diagrams or label them clearly.
7. Write limitations: SDR scope, heuristic calibration size, detector/license path, hardware, no identity/narrative scene claims.
8. Complete security/license/SBOM checks and resolve or document accepted risks.
9. Rehearse demo from a clean environment and time it.
10. Record exact commands, versions, commit, and recovery plan.
11. Tag release only after the release checklist passes.

## Required verification

```bash
uv sync --frozen --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src apps
uv run pytest -q
docker compose build --pull
docker compose up -d
uv run pytest tests/system -q
uv run cine-analyzer benchmark --manifest fixtures/benchmark/manifest.yaml --output build/release-benchmark.json
git diff --check
git status --short
```

Run the documented demo from a clean checkout or clean container volume. Confirm no private media, weights, secrets, databases, generated frames, or profiler dumps are tracked.

## Exit gate

- [ ] Clean bootstrap and Compose deployment work from documentation.
- [ ] All required suites and system smoke pass.
- [ ] Benchmark is reproducible and hardware-qualified.
- [ ] README claims match measured evidence.
- [ ] Current/future architecture is clearly distinguished.
- [ ] Demo includes graceful failure and one optimization story.
- [ ] Licensing/notices/SBOM are present.
- [ ] Release checklist is signed off and project state marks the release candidate.

## Cursor prompt

```text
Execute Phase 13 from docs/phases/phase-13-release.md. Freeze feature scope and
produce the release evidence: clean bootstrap, full verification, Compose smoke,
qualified benchmark, current architecture, sample report/screenshots, security
and licensing artifacts, limitations, and a timed demo script including graceful
failure plus one profiling story. Do not add features. Update state and stop.
```
