# Project state

## Current phase

Phase 13 complete as **0.1.0 release candidate**. Feature scope frozen.
No Phase 14 guide. Further work follows `docs/backlog.md` triggers only.

## Last verified commit

None. Phases 00–13 remain uncommitted. Tag `v0.1.0-rc.1` after the owner
commits. Benchmark `commit` field is `uncommitted`.

## Working vertical slice

Unchanged runtime: CLI SQLite (Profile A); API default is local PostgreSQL
poll; optional Celery/Redis; Streamlit HTTP-only; in-process JSON metrics;
spatial `none`/`fake`; critic `none`/`fake`/OpenAI HTTP. No Docker daemon on
the Phase 13 host, so Compose/system smoke was not executed.

## Decisions in force

Twenty-three ADRs, none added. Default config hash unchanged:
`66dced8dd50901cdfea31549d1395668fcca7bbc425288c3b705fe342d6304b7`.
Pipeline `0.1.0`. Package `0.1.0`. Current vs future architecture labelled in
`docs/architecture/system-design.md`. LICENSE appendix entity remains
“Edgar Coutiño Ocampo”.

## Open decisions

ADR-0007 Ultralytics path. Personal copyright name at public publish.
Operator `bench-01`–`bench-03` / 2160p RTF.

## Active risks

Unchanged detector false cuts on `flash.mp4`; Farneback gaps on
`tension_signals` shot 1. Compose/broker live smoke needs Docker+Redis.
Synthetic RTF does not predict 60s 1080p.

## Verification actually run

2026-09-07, CPython 3.12.7, ffmpeg 9.0.1, macOS 13.5 arm64, Postgres 16.15
on `/tmp/cine-pg-phase09` port 55433.

- `uv sync --frozen --all-groups` — passed.
- `uv lock --check` — passed.
- `uv run ruff check .` / `ruff format --check .` — 325 files.
- `uv run mypy src apps` — 119 files.
- `PYTEST_POSTGRES_URL=postgresql+pg8000://cine:@127.0.0.1:55433/cine_analyzer uv run pytest -q --cov-fail-under=100`
  — **1006 passed**, 3 skipped, **100%** (6856 statements, 1420 branches).
  Skips: Redis broker, live critic, distributed Compose smoke.
- `uv run pytest tests/system -q` — skipped (no live API).
- `docker compose build --pull` — **not run** (`docker: command not found`).
- Benchmark `build/release-benchmark.json` validated; copy at
  `docs/examples/release-benchmark.json`. `two_color_cut` cold 1552 ms /
  RTF milli 388; `tension_signals` cold 5372 ms / 1343.
- Sample report `docs/examples/sample-report.json` validates; spatial
  `detector_not_installed`; audio unavailable.
- CLI demo timed: report 3.95 s, reuse 0.44 s, `no_audio` 1.01 s,
  `tension_signals` 5.54 s (motion PARTIAL), fake critique 0.43 s.
- `git diff --check` — passed.

## Known failures

Compose/container promotion blocked without Docker. N3 2160p not run.
Operator 60s clips absent. `pip-audit` not in the dependency set.

## Deferred work

See `docs/backlog.md`. Detector extra, Prometheus, SAM 2, NVDEC, Triton,
Ray/Kubernetes, camera-movement labels, narrative grouping, LUFS.

## Notes for the next session

Do not add features. Tag only after commit. Run Compose on a Docker host
before a registry push. Do not invent 1080p numbers.

## Handoff format

Keep this file under 120 lines.
