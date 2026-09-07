# Cursor operating guide

## The central rule

Treat Cursor as a sequence of focused engineering sessions, not as a single engineer expected to remember a long specification indefinitely.

The Engineering Bible is the map. The active phase file is the work order. `docs/project-state.md` is the handoff. Source code and tests are the truth.

## Context budget per session

Load:

1. `AGENTS.md`;
2. `.cursor/rules/00-project.mdc` automatically;
3. `docs/project-state.md`;
4. exactly one `docs/phases/phase-XX-*.md`;
5. only the canonical sections and source files named by that phase.

Avoid loading:

- the whole PDF;
- every phase guide;
- entire generated schemas/logs/reports;
- model weights or frame directories;
- unrelated source packages;
- stale chat transcripts.

If a phase touches more than roughly three subsystems, split it into task packets using `prompts/TASK_PACKET_TEMPLATE.md` while preserving the phase exit gate.

## Session lifecycle

### 1. Bootstrap

Paste `prompts/BOOTSTRAP.md`, replacing the phase placeholder. Cursor should respond with outcome, likely touched areas, tests, assumptions, non-goals, and only true blockers.

### 2. Inspect

Let Cursor search narrowly for relevant symbols and tests. It should not summarize the repository recursively. Ask it to quote current behavior from exact code/tests before changing a public contract.

### 3. Implement

Use small coherent diffs. Tests should fail for the intended reason before or alongside the fix. Do not accept broad exception catches, silent fallback, unbounded queues, or placeholder production adapters.

### 4. Verify

Require actual command execution. “Should pass” is not evidence. For media/CV work, also inspect generated evidence or golden outputs rather than relying only on unit tests.

### 5. Review

Ask Cursor to inspect its own diff for:

- scope growth;
- changed schemas/formulas/state without docs/ADR;
- leaked infrastructure imports into domain code;
- unsafe shell/path handling;
- unbounded reads/queues/responses;
- nondeterministic ordering;
- generated media/weights/secrets;
- skipped or weakened tests;
- stale documentation.

### 6. Handoff and stop

Cursor updates `docs/project-state.md` under 120 lines: verified behavior, commands/results, decisions, known failures, and exact next action. Commit after human review. Start the next phase in a new chat.

## Prompt size rules

- One outcome per request.
- Name exact files or symbols when known.
- Include only the observed failure and smallest relevant log excerpt.
- Put stable rules in repository files, not repeated prose.
- Put large generated evidence in artifacts and reference its path/ID.
- Ask for a plan only when the task has meaningful design choices; otherwise ask Cursor to proceed and verify.
- Never paste model documentation, entire dependency docs, or whole stack traces when a precise excerpt will do.

## Contract-change protocol

If implementation suggests changing a public schema, metric formula, time unit, state transition, persistence invariant, or license posture, stop the coding task and create a decision packet:

```text
Decision needed: [one sentence]
Current contract: [file + exact rule]
Observed evidence: [test/benchmark/failure]
Options: [2-3 credible alternatives]
Compatibility/data impact: [specific]
Recommendation: [one choice + why]
Required ADR/migration/tests: [list]
Do not implement until the decision is accepted.
```

## Debug prompt

```text
Diagnose this failure without changing code first.

Read: AGENTS.md, docs/project-state.md, [failing test/source files only].
Reproduction: [exact command]
Observed error: [minimal excerpt]
Expected invariant: [canonical file/rule]

Return: ranked hypotheses tied to evidence, smallest discriminating checks,
and the likely fix scope. Do not weaken tests, add broad fallbacks, or edit yet.
```

After diagnosis, use a task packet for the approved fix.

## Review prompt

```text
Review the current diff as a senior Python/media-pipeline engineer. Do not edit.
Prioritize correctness, data loss, concurrency races, idempotency, schema drift,
unsafe media/subprocess handling, resource leaks, nondeterminism, and missing
failure tests. Tie every finding to a file/symbol and explain the concrete
failure scenario. Ignore style-only preferences already enforced by tools.
```

## Performance prompt

```text
Do not optimize yet. Run or inspect the documented benchmark and identify the
dominant wall-time, queue-time, RSS, GPU-memory, or artifact-size cost. Return
the evidence, one primary hypothesis, a controlled change, correctness guard,
and before/after experiment. Reject any optimization that changes sampling or
metric semantics without an evaluation and method-version decision.
```

## When to start a fresh chat

Start fresh after a phase, after a major ADR, after a schema migration, when Cursor repeats stale assumptions, or when unrelated files dominate the context. Preserve continuity through committed code, tests, ADRs, and `docs/project-state.md` rather than pasting the old conversation.

## Human review checkpoints

The project owner must personally review:

- product/non-goals and all ADRs;
- detector/license choice;
- public report schema and metric wording;
- framing/lighting calibration examples;
- security/retention behavior;
- benchmark claims;
- screenshots/demo footage rights;
- final release diff.
