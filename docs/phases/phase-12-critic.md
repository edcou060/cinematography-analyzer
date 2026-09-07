# Phase 12 - Optional evidence-bounded AI critic

## Mission

Add a replaceable, non-authoritative prose layer that summarizes only validated report evidence. Analysis must remain complete when the critic is disabled or unavailable.

## Context budget

Read only:

- `AGENTS.md`
- `docs/project-state.md`
- critic/privacy/model ADRs
- `docs/contracts/data-contracts.md` sections 9 and 11
- `docs/metrics/metric-definitions.md` sections 1, 8, and 10
- `docs/architecture/system-design.md` sections 3, 6, and 7
- current report/API/worker adapters and focused tests
- this phase guide

## Deliverables

- `Critic` port plus no-op and deterministic fake adapters.
- Compact `CriticInput` schema derived from the report, excluding frames, paths, raw filenames, and unsupported metadata.
- Versioned system prompt and output schema.
- Optional Ollama or OpenAI-compatible/vLLM adapter selected by ADR.
- Critique stage/queue isolated from report completion.
- Validation, caching by input hash/prompt/model identity, timeout, and safe failure.
- Dashboard section labeled interpreted/optional with exact evidence chips.

## Critic contract

The critic may mention only fields present in `CriticInput`, use cautious language for estimates, produce at most three concise sentences or a small structured response, and never infer director, genre, story, emotion, budget, camera/lens, or artistic quality unless those are explicitly measured (they are not in MVP).

Example input:

```json
{
  "schema_version": "1.0",
  "editing": {"shot_count": 18, "asl_seconds": 3.42, "median_seconds": 2.80},
  "lighting": {"low_key_ratio": 0.62, "valid_shot_ratio": 0.94},
  "palette": ["#17212B", "#A66B42", "#D5C2A8"],
  "composition": {"valid_shot_ratio": 0.71, "median_thirds_proximity": 0.78},
  "tension_proxy": {"peak_seconds": [12.0, 37.5], "audio_available": true}
}
```

## Steps

1. Decide whether this feature materially improves the portfolio. Skipping it is valid.
2. Define the minimal `CriticInput`; aggregate and round values intentionally to reduce tokens and false precision.
3. Remove user-controlled filename/text from the prompt or delimit it as untrusted if a future use requires it.
4. Write a strict system prompt: use only supplied facts, identify estimates, no hidden assumptions, concise output.
5. Prefer structured output when supported; validate with Pydantic and a hard length limit.
6. Set low temperature/deterministic settings where supported and record them.
7. Cache by validated input hash + prompt version + model/adapter identity.
8. Apply timeout/token limit; failure returns a valid omitted/unavailable critique.
9. Use a fake critic for CI. Add adversarial inputs with suspicious strings and missing metrics.
10. Add a lightweight claim audit: numbers/colors/labels appearing in prose must map to allowed input values; otherwise reject or regenerate once.
11. Store prose separately so it can be deleted/regenerated without changing metrics.
12. Show source metric chips and an “AI interpretation” label in the dashboard.

## Required verification

```bash
uv run pytest tests/unit/critic tests/contract/critic tests/integration/critic_fake -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src apps
uv run cine-analyzer critique build/report.json --backend fake
```

If a real local server is enabled, run one marked smoke test and record model, prompt version, sampling settings, timeout, and input hash. Do not require it in default CI.

## Exit gate

- [ ] Critic receives no frames or sensitive paths/names.
- [ ] Output is strict, short, validated, and labeled interpretation.
- [ ] Unsupported claims/numbers are rejected.
- [ ] Critic failure cannot fail the analysis.
- [ ] Cache identity includes prompt/model/input.
- [ ] Core report is unchanged with critic disabled.
- [ ] `docs/project-state.md` points to Phase 13.

## Cursor prompt

```text
Execute Phase 12 from docs/phases/phase-12-critic.md only if its ADR is accepted.
Add a replaceable, optional prose critic over a compact validated metrics-only
input. Use a fake for CI, strict short output, claim checks, caching, timeout,
and graceful omission. It must never modify/fail measured analysis. Do not pass
frames or filenames. Verify, update project state, and stop.
```
