# Phase 03 - Safe ingestion, probing, and analysis identity

## Mission

Implement a local CLI/use-case path that streams a file into an artifact store, hashes it, safely probes it with ffprobe, validates limits, and creates/reuses an analysis identity. Use a repository port with a simple tested adapter; no web upload yet.

## Context budget

Read only:

- `docs/project-state.md`
- ingestion/artifact ADRs
- `docs/architecture/system-design.md` sections 4, 6, 8, 10, and 13
- `docs/contracts/data-contracts.md` sections 1-4 and 10-13
- `docs/operations/quality-and-operations.md` sections 5-9
- this phase guide

## Deliverables

- `ArtifactStore`, `MediaProbe`, and `AnalysisRepository` protocols.
- Filesystem artifact store with temporary-write/checksum/atomic-promotion behavior.
- ffprobe adapter using argument arrays, JSON output, timeout, and bounded stderr.
- `IngestVideo` and `CreateAnalysis` application use cases.
- Local SQLite repository if needed for a runnable slice, with migrations or an explicit disposable-test role.
- CLI: `cine-analyzer ingest PATH` and `cine-analyzer analyze PATH --dry-run` returning IDs/config hash.
- Tiny valid, corrupt, rotated, no-audio, and limit-violation fixtures.

## Steps

1. Define ports in application-facing modules; no adapter types leak into domain models.
2. Stream input chunks while computing SHA-256 and enforcing max bytes.
3. Store under generated/content-addressed keys; sanitize original filename as metadata only.
4. Run ffprobe with `shell=False`, timeout, process-group cleanup, JSON writer, and selected fields.
5. Normalize rational frame rates, display rotation, duration, dimensions, codec, pixel format, audio presence, and transfer characteristics.
6. Validate configured duration/resolution/stream/HDR rules.
7. Persist or reuse video identity by content hash.
8. Validate and hash the analysis config; persist or reuse analysis identity by video/config/pipeline version.
9. Ensure failure removes only known temporary artifacts and records a safe error.
10. Test filenames containing spaces, Unicode, leading hyphens, and shell metacharacters without ever interpolating a shell command.

## Required verification

```bash
uv run pytest tests/unit/adapters tests/integration/media tests/integration/ingestion -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run cine-analyzer ingest fixtures/video/two_color_cut.mp4
uv run cine-analyzer analyze fixtures/video/two_color_cut.mp4 --dry-run
```

Run the dry-run twice and prove analysis identity reuse. Verify corrupt/oversized media produces a stable safe error and no canonical orphan.

## Exit gate

- [ ] Input is streamed and bounded.
- [ ] ffprobe invocation cannot be shell-injected.
- [ ] Probe metadata is validated into strict contracts.
- [ ] Artifact writes are atomic and checksummed.
- [ ] Repeated semantic requests reuse identity.
- [ ] Unsupported media fails before analysis.
- [ ] `docs/project-state.md` points to Phase 04.
