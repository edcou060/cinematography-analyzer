# Cursor task packet

Use this template for a bug, refactor, or feature that does not map cleanly to one roadmap phase.

## Outcome

One observable result.

## Context budget

Read only:

- `AGENTS.md`
- `docs/project-state.md`
- `[specific canonical document]`
- `[specific source/test files]`

## Evidence

- Current behavior:
- Expected behavior:
- Reproduction command or fixture:

## Allowed changes

- `[packages/files]`

## Non-goals

- `[explicit exclusions]`

## Invariants

- `[contracts that may not change]`

## Required verification

```bash
[focused test]
[lint/type checks]
```

## Exit gate

- [ ] Expected behavior is covered by a failing-then-passing test.
- [ ] No unrelated public contract changed.
- [ ] Actual command results are reported.
- [ ] `docs/project-state.md` is updated if project state changed.

## Stop conditions

Stop and ask one focused question if the fix requires a schema migration, a metric-definition change, deletion of user data, a new paid service, or a licensing decision.
