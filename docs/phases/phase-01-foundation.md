# Phase 01 - Python foundation and quality gates

## Mission

Create the smallest executable repository with reliable tooling, configuration loading, logging, and a health-tested package. Do not implement media analysis yet.

## Context budget

Read only:

- `docs/project-state.md`
- accepted foundation-related ADRs
- `docs/architecture/system-design.md` sections 5, 13, 15, and 17
- `docs/operations/quality-and-operations.md` sections 1-3 and 12
- this phase guide

## Deliverables

- `pyproject.toml`, `.python-version`, and committed `uv.lock`.
- `src/cine_analyzer/` with version, settings, logging setup, and a minimal CLI.
- `tests/unit/` with package/settings/logging smoke tests.
- `Makefile` or equivalent transparent command aliases.
- CI running lock check, Ruff, mypy, and unit tests.
- `compose.yaml` only if it contains a minimal, actually tested dependency; otherwise defer it.

## Dependency rule

Add only foundational packages used now: Pydantic, pydantic-settings, structured logging choice, pytest, Hypothesis, coverage, Ruff, and mypy. Do not add OpenCV, PyTorch, Ultralytics, SAM 2, Celery, Streamlit, or database drivers yet.

## Steps

1. Initialize a `src/` package and set Python 3.12.
2. Configure dependency groups: core and dev. Keep optional future groups out until used.
3. Configure Ruff and mypy in `pyproject.toml`; document any intentionally relaxed mypy rule.
4. Implement one immutable settings boundary. Environment variables are read only there.
5. Implement structured logging that can bind request/analysis/stage context without global mutable IDs.
6. Implement `python -m cine_analyzer --version` and `cine-analyzer doctor` checking runtime and FFmpeg availability without requiring it yet.
7. Add unit tests for default settings, invalid values, environment override, version command, and safe log serialization.
8. Add CI with dependency cache but no media/model downloads.
9. Run from a clean environment using only documented commands.

## Required verification

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run python -m cine_analyzer --version
uv run cine-analyzer doctor
```

Record exact results. `doctor` may report FFmpeg unavailable as a diagnosed capability only if the project contract allows it at this phase.

## Exit gate

- [ ] Clean clone setup is documented and works.
- [ ] No unused production dependency exists.
- [ ] Package imports do not trigger I/O, model loading, or environment mutation.
- [ ] CI and local checks use the same commands.
- [ ] Logs are structured and tested.
- [ ] `docs/project-state.md` points to Phase 02.
