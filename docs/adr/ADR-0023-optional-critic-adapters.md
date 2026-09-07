# ADR-0023: Optional critic adapters without a model SDK

- Status: Accepted
- Date: 2026-09-07
- Owners: project owner
- Supersedes: none (ADR-0005 remains in force)

## Context

Phase 12 requires a replaceable, non-authoritative prose layer over a compact
validated metrics-only input. ADR-0005 already forbids the critic from writing
metrics or failing analysis. The remaining choice is how to talk to a model
without expanding the base install or putting endpoints in the hashed config.

Ollama and vLLM client libraries would add licence/SBOM surface before a
measured need. Putting `enabled` plus a URL in `AnalysisConfig` would change
the default config hash and mix deployment secrets into analysis identity.

## Decision

Keep `CriticConfig.enabled` as the only hashed critic field (default `false`).
Adapter choice and endpoints live in `Settings`:

- `none` — omit interpretation (process default).
- `fake` — deterministic, metrics-only sentences for CI and `cine-analyzer critique --backend fake`.
- `openai` — optional OpenAI-compatible HTTP (`/v1/chat/completions`) via the
  existing `httpx` dependency. No Ollama SDK, no vLLM package.

The system prompt is versioned (`critic-prompt-v1`). Cache identity is
SHA-256 of canonical `CriticInput` JSON + prompt version + adapter identity.
Prose is stored in `critique_runs`, not in the report artifact. A critic
timeout, audit rejection, or transport failure yields a valid omitted
critique (`FAILED` / no text) and never changes analysis state.

CI uses the fake. A live local server is an optional marked smoke test, not
a default gate.

## Alternatives considered

**Ollama Python client in a `critic` extra.** Rejected: extra dependency for
one HTTP POST the base install can already make.

**vLLM as a required runtime.** Rejected: premature for the MVP base install. An
OpenAI-compatible URL can point at vLLM later without a new package.

**Hash model name and temperature into `AnalysisConfig`.** Rejected: those are
deployment/prompt settings; enabling the critic already changes identity via
`critic.enabled`.

## Consequences

Easier: default config hash stays
`66dced8dd50901cdfea31549d1395668fcca7bbc425288c3b705fe342d6304b7`. Tests run
without a model server. Operators can point `CINE_CRITIC_BASE_URL` at any
compatible local server.

Harder: the OpenAI-compatible adapter is a thin HTTP client, not a full
provider SDK. Streaming, tool calls, and multi-turn chat are out of scope.

## Verification

Unit tests: compact input omits filenames/paths; fake output passes claim
audit; adversarial numbers/labels are rejected; timeout/unavailable become
omitted critiques; cache key includes prompt/model/input. Golden/report
bytes stay identical with the critic disabled. `cine-analyzer critique
--backend fake` exits 0 on a fixture report.

## Revisit trigger

A requirement to pin a specific local model package, or evidence that HTTP
JSON mode is insufficient for the bounded three-sentence contract.
