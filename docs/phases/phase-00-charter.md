# Phase 00 - Charter and irreversible decisions

## Mission

Turn the concept into a testable product contract before code exists. This phase removes ambiguous language, records scope, and creates the decision structure that later Cursor sessions must respect.

## Context budget

Read only:

- `AGENTS.md`
- `docs/project-state.md`
- `docs/architecture/system-design.md` sections 1-4, 14, and 16
- `docs/architecture/decision-log.md`
- this phase guide

## Deliverables

1. `README.md` with problem, demo workflow, MVP scope, non-goals, architecture thumbnail, and roadmap.
2. `docs/product-contract.md` defining supported input, report outcomes, user-visible caveats, and success metrics.
3. `docs/adr/ADR-0001` through `ADR-0007` from the proposed decision log.
4. `LICENSE` and `THIRD_PARTY_NOTICES.md` strategy. If the detector license path is not decided, keep the real adapter out of the base install and mark the decision blocked.
5. `.gitignore` covering media, frames, weights, reports, databases, secrets, caches, and profiler output.
6. Updated `docs/project-state.md`.

## Steps

1. State the intended public release model: fully open-source portfolio, private prototype, or detector-neutral until a license choice is made.
2. Define MVP input: local upload, SDR, supported containers/codecs as validated by probe, default duration/size/resolution ceilings.
3. Define MVP output: shot list, editing summary, per-shot palette/lightness, optional spatial/audio availability, evidence, and report JSON.
4. Define vocabulary exactly: shot, boundary, narrative scene, estimated, measured, interpreted, unavailable.
5. Accept or revise each proposed ADR. Keep alternatives and revisit triggers concrete.
6. Define three benchmark clips and one end-to-end demo story using self-created or redistributable footage.
7. Write a release checklist with measurable conditions.
8. Check every document for claims that exceed the MVP.

## Required verification

This phase is documentation-only. Verify with searches:

```bash
rg -n "narrative scene|composition quality|detect.*director|guarantee" README.md docs
rg -n "TODO|TBD|UNSET" README.md docs
git diff --check
```

Every remaining TODO/TBD must name an owner phase or true blocking decision.

## Exit gate

- [ ] A reviewer can say what enters, what exits, and what is explicitly not built.
- [ ] The seven initial ADRs are accepted/rejected/superseded, not left as vague prose.
- [ ] The detector licensing path is decided or the adapter is explicitly gated.
- [ ] The demo and benchmark inputs are legally usable.
- [ ] No code scaffold has been created prematurely.
- [ ] `docs/project-state.md` points to Phase 01.

## Cursor prompt

```text
Execute Phase 00 from docs/phases/phase-00-charter.md. Work only on product
contract, ADRs, release/licensing posture, ignore rules, and README framing.
Do not scaffold Python packages or add dependencies. Resolve contradictions
between the concept and the canonical architecture explicitly. Run the stated
document checks, update docs/project-state.md, and stop at the Phase 00 gate.
```
