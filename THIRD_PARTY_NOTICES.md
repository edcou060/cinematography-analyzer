# Third-party notices

This file records the licence posture of software this project depends on, gates, or deliberately defers. The project's own code is licensed under Apache-2.0; see `LICENSE` and `docs/adr/ADR-0008-release-model-and-license.md`.

This is engineering documentation written to keep the distributed artifact consistent with its declared licence. It is not legal advice.

## How this file is maintained

Phase 00 establishes the strategy and records the components whose posture is already a decision. It does not enumerate dependency licences, because the project has no dependencies yet: no `pyproject.toml`, no `uv.lock`, nothing installed.

From Phase 01 onward:

1. The dependency table below is **generated from `uv.lock`**, so every entry names the package version actually resolved. Licence identifiers are read from package metadata, never recalled from memory.
2. A dependency may be added only when it is used in the active phase, and only if its licence permits distribution under this project's declared licence.
3. A component whose licence conflicts with Apache-2.0 distribution is either kept out of the base installation behind an optional extra with an explicit opt-in, or not used.
4. Any component carrying a copyleft or source-available licence gets a row in the gated table below, with the release-level decision that governs it.
5. Regenerating this file and confirming the base install carries no conflicting licence are both blocking items in `docs/release-checklist.md`.

## Base installation dependencies

Every package `uv.lock` resolves for the base install, directly or transitively. Versions come from the lockfile and licence declarations are read from the installed package metadata. `tests/unit/test_supply_chain.py` fails if this table drifts from the lockfile, if a declaration is not one an Apache-2.0 distribution can carry, or if a gated component appears anywhere in the resolution.

| Package | Version | Licence | Why it is here |
| --- | --- | --- | --- |
| `alembic` | `1.19.2` | MIT | Direct: PostgreSQL schema migrations (ADR-0018) |
| `annotated-doc` | `0.0.5` | MIT | Transitive: FastAPI OpenAPI documentation helpers |
| `annotated-types` | `0.8.0` | MIT | Transitive: constraint types used by Pydantic |
| `anyio` | `4.15.1` | MIT | Transitive: FastAPI/Starlette async primitives |
| `asn1crypto` | `1.5.1` | MIT | Transitive: pg8000 SCRAM authentication helper |
| `av` | `15.1.0` | BSD-3-Clause | Direct: ordered sample extraction (ADR-0009) |
| `certifi` | `2026.7.22` | MPL-2.0 | Transitive: httpx CA bundle |
| `click` | `8.5.0` | BSD-3-Clause | Transitive: Uvicorn/PySceneDetect CLI toolkit; this project does not invoke PySceneDetect's CLI |
| `cloudpickle` | `3.1.2` | BSD-3-Clause | Transitive: Joblib serialization helper used by scikit-learn |
| `fastapi` | `0.141.1` | MIT | Direct: HTTP control plane (ADR-0019) |
| `greenlet` | `3.5.5` | MIT AND PSF-2.0 | Direct: SQLAlchemy native helper; declared so the licence table is platform-stable |
| `h11` | `0.16.0` | MIT | Transitive: Uvicorn HTTP/1.1 implementation |
| `httpcore` | `1.0.9` | BSD-3-Clause | Transitive: httpx HTTP transport |
| `httpx` | `0.28.1` | BSD-3-Clause | Direct: typed dashboard HTTP client (ADR-0020) |
| `idna` | `3.19` | BSD-3-Clause | Transitive: anyio/httpcore internationalized domain names |
| `joblib` | `1.6.0` | BSD-3-Clause | Transitive: scikit-learn parallelism helper |
| `mako` | `1.4.1` | MIT | Transitive: Alembic migration template renderer |
| `markupsafe` | `3.0.3` | BSD-3-Clause | Transitive: Mako HTML/XML escaping helper |
| `narwhals` | `2.25.0` | MIT | Transitive: scikit-learn dataframe compatibility helper |
| `numpy` | `2.5.2` | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Direct: array storage for decoded frames |
| `opencv-python` | `4.14.0.94` | Apache 2.0 | Direct: PySceneDetect decode, JPEG evidence, float CIE Lab (ADR-0012) |
| `pg8000` | `1.31.5` | BSD 3-Clause License | Direct: PostgreSQL driver (ADR-0018) |
| `platformdirs` | `4.11.7` | MIT | Transitive: PySceneDetect path helper; this project does not invoke it |
| `pydantic` | `2.13.5` | MIT | Direct: strict boundary validation |
| `pydantic-core` | `2.46.5` | MIT | Transitive: Pydantic's validation core |
| `pydantic-settings` | `2.15.0` | MIT | Direct: the environment-variable settings boundary |
| `python-dateutil` | `2.9.0.post0` | Dual License | Transitive: pg8000 timestamp parsing helper |
| `python-dotenv` | `1.2.3` | BSD-3-Clause | Transitive: pydantic-settings dependency; no `.env` file is read by this project |
| `python-multipart` | `0.0.32` | Apache-2.0 | Direct: streamed multipart uploads |
| `scenedetect` | `0.7.1` | BSD-3-Clause | Direct: pinned shot-boundary detector, translated to domain shots |
| `scikit-learn` | `1.9.0` | BSD-3-Clause | Direct: deterministic MiniBatchKMeans palettes (ADR-0012) |
| `scipy` | `1.18.1` | License :: OSI Approved :: BSD License | Transitive: scikit-learn scientific core |
| `scramp` | `1.4.17` | MIT No Attribution | Transitive: pg8000 SCRAM authentication |
| `six` | `1.17.0` | MIT | Transitive: python-dateutil compatibility helper |
| `sqlalchemy` | `2.0.52` | MIT | Direct: PostgreSQL persistence (ADR-0018) |
| `starlette` | `1.6.0` | BSD-3-Clause | Transitive: FastAPI HTTP toolkit |
| `structlog` | `25.5.0` | MIT OR Apache-2.0 | Direct: structured logging and contextvar-bound correlation fields |
| `threadpoolctl` | `3.6.0` | BSD-3-Clause | Transitive: native thread-pool control used by scikit-learn |
| `tqdm` | `4.70.0` | MPL-2.0 AND MIT | Transitive: PySceneDetect progress helper; this project disables progress output |
| `typing-extensions` | `4.16.0` | PSF-2.0 | Transitive: typing backports used by Pydantic |
| `typing-inspection` | `0.4.4` | MIT | Transitive: Pydantic annotation introspection |
| `uvicorn` | `0.52.4` | BSD-3-Clause | Direct: ASGI server for the control plane (ADR-0019) |

Development-only packages (`hypothesis`, `mypy`, `pytest`, `pytest-cov`, `ruff`, and their transitive dependencies) are not distributed with the project and are therefore not listed here. The `dashboard` group (`streamlit`, `plotly`, and their transitive dependencies) is an optional UI install and is likewise omitted from this base-install table. They are still covered by the gating check: a gated component may not appear anywhere in `uv.lock`.

## Components with a decided posture

These are not yet installed. Their posture is recorded now because it is a release-level decision, not a dependency detail.

| Component | Role | Licence situation | Posture | Governing decision |
| --- | --- | --- | --- | --- |
| Ultralytics YOLO | Person detection for the spatial pillar | Published as AGPL-3.0 or paid Enterprise (`https://www.ultralytics.com/license`) | **Gated.** Never a base or transitive dependency. Optional extra, explicit configuration, explicit opt-in acknowledgement at install. Weights fetched by the operator and recorded by digest | `docs/adr/ADR-0007-ultralytics-license-gate.md` |
| Meta SAM 2 | Mask refinement | Code and checkpoints carry separate terms that must each be read | **Deferred.** Not adopted in the MVP. Entering it requires an ADR recording both the code licence and the checkpoint terms | `docs/architecture/system-design.md` section 16 |
| FFmpeg and ffprobe | Container probing, decoding, proxy and fixture generation | Build-dependent: LGPL or GPL according to how the binary was configured | **External process.** Invoked as a separate executable with an argument array, never linked into this codebase, so no code is combined. The operator supplies the binary; any redistributed build must have its own configuration and licence recorded | `docs/adr/ADR-0004-queue-payloads-are-references.md` (process boundary), Phase 03 |
| Redis server | Task transport and cache | Recent server versions ship under source-available terms rather than a classic open-source licence; the Python client is separate | **External service.** Run by the operator, never redistributed by this project. Only the client library becomes a dependency, and it appears in the generated table | `docs/adr/ADR-0003-postgres-authoritative-redis-transport.md` |
| PostgreSQL server | Authoritative job state | PostgreSQL Licence, permissive | **External service.** Run by the operator, never redistributed | `docs/adr/ADR-0003-postgres-authoritative-redis-transport.md` |
| Language model weights for the optional critic | Interpretation prose | Weight licences vary per model and are frequently more restrictive than the serving framework's | **Deferred and optional.** The critic is disabled by default. No weights are vendored. Selecting a model requires recording that model's weight licence | `docs/adr/ADR-0005-measurement-separate-from-interpretation.md`, Phase 12 |

Licence identifiers in the third column are a Phase 00 snapshot taken from the upstream sources listed in `docs/reference-sources.md` (snapshot 2026-09-06). Upstream terms change. Each row is re-checked against the actual artifact when the component is first installed, and again before release.

## Media, weights, and generated artifacts

No video, audio, extracted frame, model weight, or generated report is committed to this repository or redistributed with it. `.gitignore` blocks these at every path.

Benchmark and demo inputs are limited to footage the project owner created and synthetic clips generated by FFmpeg from its built-in sources, per `docs/product-contract.md` section 7. Commercially released film and television material is not committed, redistributed, or shown in published reports, screenshots, or recordings.

## Attribution

Third-party attribution required by a dependency's licence — retained copyright notices, `NOTICE` file contents, and licence texts — is reproduced in the generated table's per-component entries from Phase 01. Where a licence requires the full text to accompany distribution, that text is included rather than linked.

A CycloneDX 1.5 document of the same base-install closure is `docs/examples/sbom-cyclonedx.json`.
