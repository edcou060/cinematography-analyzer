# Phase 02 - Domain contracts and state rules

## Mission

Implement strict, framework-independent domain models, canonical configuration hashing, and tested job/stage transitions. This phase creates no database and invokes no media tools.

## Context budget

Read only:

- `docs/project-state.md`
- accepted schema/time/state ADRs
- `docs/contracts/data-contracts.md`
- `docs/architecture/system-design.md` sections 10-14
- this phase guide

## Deliverables

- `src/cine_analyzer/domain/` modules grouped by media, time, shots, measurements, chromatics, spatial, timeline, report, jobs, and errors.
- `src/cine_analyzer/domain/config.py` with canonicalizable analysis configuration.
- Pure state-transition functions or an aggregate enforcing legal transitions.
- Public JSON-schema snapshots in `tests/contract/snapshots/`.
- Unit/property/round-trip tests.

## Steps

1. Implement shared constrained types and `StrictModel` with `extra="forbid"`.
2. Implement `TimeRangeMs` and prove ordering/duration invariants with Hypothesis.
3. Implement artifact, evidence, and provenance contracts.
4. Implement shot/boundary/sampling contracts. Enforce contiguous ordered shot sets.
5. Implement generic or explicit measurement envelopes with value/status consistency.
6. Implement chromatic, spatial, temporal, audio, timeline, summary, and report shapes. Keep future fields optional only when absence semantics are explicit.
7. Implement job/stage states and legal transition table. Terminal states cannot regress.
8. Implement canonical config JSON/hash. Snapshot representative hashes.
9. Generate JSON schemas and snapshot them. Review field descriptions and units.
10. Ensure domain modules import no FastAPI, Celery, SQLAlchemy, Streamlit, OpenCV, NumPy, PyTorch, or detector SDK.

## Required verification

```bash
uv run pytest tests/unit/domain tests/contract -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
rg -n "fastapi|celery|sqlalchemy|streamlit|cv2|torch|ultralytics" src/cine_analyzer/domain
```

The final search must be empty unless a string appears in documentation metadata with a justified test.

## Exit gate

- [ ] Unknown data is rejected at boundaries.
- [ ] All time values at durable boundaries are integer milliseconds.
- [ ] Missing metrics carry status/reason, never unexplained nulls.
- [ ] Legal and illegal job transitions are tested.
- [ ] Config hashing is deterministic.
- [ ] JSON schema snapshots are reviewed.
- [ ] Domain package is infrastructure-free.
- [ ] `docs/project-state.md` points to Phase 03.
