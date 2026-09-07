# Security and supply-chain scan (Phase 13)

Recorded 2026-09-07 on the development host. Commands were actually run.

## What ran

| Check | Result |
| --- | --- |
| `uv lock --check` | Passed (93 packages resolved against the lockfile). |
| `uv sync --frozen --all-groups` | Passed. |
| Base-install licence table vs `uv.lock` | `tests/unit/test_supply_chain.py` (P3–P5). No `ultralytics` node. |
| CycloneDX SBOM vs lockfile closure | `docs/examples/sbom-cyclonedx.json` (42 library components). |
| Tracked-file secret patterns | No PEM private-key headers, AWS access-key prefixes, or Stripe live secret prefixes in non-ignored sources. |
| Tracked media / weights / databases | `.gitignore` plus hygiene test; `fixtures/video/*.mp4` exist locally and are not tracked. |
| `pip-audit` / `uv pip audit` | Not in the dependency set. Not run. Adding it is a backlog trigger once a published image exists. |
| Container CVE scan (`docker compose build`) | **Not run.** This host has no Docker / Colima / Podman daemon. |

## Accepted residual risk

From `docs/operations/threat-model.md`: native parsers (FFmpeg, PyAV, OpenCV)
can still fault. Isolation is timeout, rlimit, and process boundaries. Artifact
UUIDs are capabilities. Quota checks are not a distributed lock.

Compose images, when built, must be scanned on a Docker host before a public
registry push. That push is not part of this candidate.

## Regeneration

SBOM components are the transitive base install from `uv.lock`, same closure as
`THIRD_PARTY_NOTICES.md`. If the lockfile changes, update both files; the unit
tests fail on drift.
