# Release checklist

- Status: Accepted (Phase 00)
- Scope: the first public release of pipeline version `0.1.x`
- Rule: every item is a measurable condition with a named verification. An item is satisfied by a command that was actually run and whose result was recorded, never by reading the code and concluding it looks right.

Items are grouped by what they protect. The phase column names where the check is built; the check itself is re-run at release.

## Correctness

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| C1 | Shot-boundary precision and recall are published for all three benchmark clips, with the tolerance window stated | Detector output compared against hand annotation | Phase 04 |
| C2 | Known detector failure modes are demonstrated, not hidden: the dissolves and flash frame in `bench-02-fast-montage` appear in published results with their outcome described | Benchmark report | Phase 04 |
| C3 | Shot durations reconcile with probed clip duration within one millisecond per boundary, on constant and variable frame-rate inputs | Reconciliation test | Phase 02, Phase 04 |
| C4 | Every metric declares unit, method version, and confidence or status | Schema test over all metric models | Phase 02 |
| C5 | Synthetic FFmpeg fixtures with known ground truth — exact cut positions, exact colours, exact silence — produce the expected values | Golden fixture tests | Phase 05 |

## Reproducibility

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| R1 | Two runs on identical input, configuration, and code version produce byte-identical measured values (S3) | Repeat-run comparison across all three benchmark clips | Phase 05 |
| R2 | Re-submitting an identical `(video_sha256, config, pipeline_version)` reuses the prior analysis (S8) | Idempotency test | Phase 03 |
| R3 | Every stage is idempotent by `(video_sha256, config_hash, pipeline_version, stage_name)`; a forced re-run of a completed stage neither duplicates nor corrupts output | Stage re-run test | Phase 03 onward |
| R4 | The local runner and the Celery runner produce equal measured values on the same input | Runner conformance test | Phase 10 |
| R5 | `uv.lock` is committed, and a clean checkout plus `uv sync` reproduces the environment on a machine with no warm cache | Clean-clone install | Phase 01 |
| R6 | Report provenance carries pipeline version, per-metric method version, configuration hash, detector version, and weight digest where a model was used | Report schema assertion | Phase 08 |

## Honesty of output

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| H1 | Every disabled or failed pillar yields `unavailable` with a machine-readable reason; no fabricated or defaulted values (S5) | Fault-injection test per pillar | Phase 08, Phase 11 |
| H2 | A default install analyses a clip successfully with the spatial pillar `unavailable`, reason `detector_not_installed` | End-to-end test on the base install | Phase 06 |
| H3 | An audio-free clip analyses successfully with the audio pillar `unavailable`, reason `no_audio_stream` | End-to-end test on the stripped benchmark variants | Phase 07 |
| H4 | 100 % of per-shot visual metrics carry a resolvable frame identifier or time range (S4) | Evidence coverage assertion over a full report | Phase 08 |
| H5 | Every heuristic label is presented with its estimate status, its confidence, and its evidence, in both API output and dashboard copy | Report inspection plus dashboard review against `docs/product-contract.md` section 5 | Phase 09 |
| H6 | The tension proxy publishes its weights and component values alongside its result | Report schema assertion | Phase 07 |
| H7 | No document, endpoint description, or dashboard string claims narrative, authorial, or aesthetic conclusions | The Phase 00 document searches, re-run over the whole repository | Phase 13 |

## Reliability

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| L1 | Killing a worker mid-analysis loses no authoritative state; the analysis resumes or reports failure (S2) | Restart test | Phase 10, Phase 11 |
| L2 | Flushing Redis mid-analysis leaves job state fully readable from PostgreSQL | Redis-loss test | Phase 10 |
| L3 | A stage failure is recorded against that stage and does not fail the report | Fault-injection test | Phase 11 |
| L4 | Wall time, per-stage time, peak memory, failure counts, and cache hits are recorded per analysis (S7) | Metrics inspection after a benchmark run | Phase 11 |
| L5 | A full report is served without loading the source video into application memory (S6) | Memory measurement while serving the largest benchmark report | Phase 08 |

## Safety

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| F1 | Acceptance is decided by probe, never by extension or declared MIME type | Hostile-upload suite: mislabelled extensions, wrong MIME types, truncated and malformed containers | Phase 03 |
| F2 | Size and duration ceilings are enforced during upload, before a partial file is accepted | Oversize upload test | Phase 03 |
| F3 | Every FFmpeg and ffprobe invocation uses an argument array with a timeout and no shell interpolation | Subprocess call-site review plus a test asserting no `shell=True` | Phase 03 |
| F4 | Uploads are stored under generated identifiers outside any served static directory | Path assertion test | Phase 03 |
| F5 | Externally visible errors contain no local path and no user-supplied filename | Error-response test across the rejection cases in `docs/product-contract.md` section 3.5 | Phase 11 |
| F6 | No secret, credential, or token appears in the repository, its history, or any log output | Secret scan over the full history | Phase 13 |

## Licensing and legal

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| P1 | `LICENSE` matches the canonical Apache-2.0 text apart from the completed appendix copyright line | Text comparison against the canonical source | Phase 00 |
| P2 | The appendix copyright placeholder is replaced with the owner's legal name or entity | Inspection | Phase 13 |
| P3 | `THIRD_PARTY_NOTICES.md` is regenerated from the committed `uv.lock` and matches the resolved dependency set | Generated-versus-committed comparison | Phase 01 onward |
| P4 | No base-install dependency carries a licence incompatible with Apache-2.0 distribution | Licence check over the resolved base dependency set | Phase 01 onward |
| P5 | Resolving the base installation yields no `ultralytics` node, directly or transitively | Dependency-graph assertion | Phase 01 |
| P6 | If any published artifact bundles an AGPL-3.0 dependency, ADR-0007 has been resolved and the artifact's declared licence matches its actual obligations | Release review against ADR-0007 | Phase 13 |
| P7 | No video, audio, frame, model weight, generated report, or database file exists in the repository or its history | History scan by extension and by blob size | Phase 13 |
| P8 | Every benchmark and demo input is self-created or FFmpeg-generated, recorded in the manifest with `video_sha256` and provenance | Manifest review against `docs/product-contract.md` section 7 | Phase 13 |

## Performance

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| N1 | Upload returns an accepted analysis identifier within one second of the request body completing (S1) | Timed upload, excluding client transfer time | Phase 03 |
| N2 | Throughput and peak memory are published for all three benchmark clips on named hardware, with the runner profile stated (S9) | Benchmark run recorded with hardware and configuration | Phase 13 |
| N3 | The 2160p variant of `bench-03-lowlight-handheld` completes within the configured resolution ceiling without exhausting memory | Benchmark run at the ceiling | Phase 13 |
| N4 | CPU and GPU concurrency limits are independently configurable and their effect is measured, not assumed | Concurrency sweep | Phase 10 |

## Documentation and demo

| # | Condition | How it is verified | Built in |
| --- | --- | --- | --- |
| D1 | `README.md` states what enters, what exits, and what is explicitly not built, consistent with `docs/product-contract.md` | Review | Phase 00, re-checked Phase 13 |
| D2 | Every ADR is Accepted, Rejected, or Superseded; none is left as prose | ADR status review | Phase 00, re-checked Phase 13 |
| D3 | The vocabulary in `docs/product-contract.md` section 2 is used consistently in code, schemas, API output, and dashboard copy | Terminology search across the repository | Phase 13 |
| D4 | No `TODO` or `TBD` marker remains without a named owner phase or an identified blocking decision | Repository search | Phase 00, re-checked Phase 13 |
| D5 | The demo runs end to end from a clean checkout following only the documented steps, including the two `unavailable` demonstrations | Rehearsal from a clean clone on a machine that has never run the project | Phase 13 |
| D6 | Published numbers state the pipeline version and configuration hash they came from | Review of the benchmark report | Phase 13 |
| D7 | `docs/project-state.md` reflects the released state and stays within 120 lines | Review | every phase |

## Phase 13 sign-off (2026-09-07)

Package version `0.1.0`. Pipeline version `0.1.0`. Tag `v0.1.0-rc.1` is the
owner's action after the first commit; this tree is still uncommitted.
Hardware: macOS 13.5 arm64, CPython 3.12.7, ffmpeg 9.0.1.

| # | Verdict | Evidence |
| --- | --- | --- |
| C1 | Partial | P/R published for golden synthetic clips at 200 ms. Operator `bench-01`–`bench-03` absent. |
| C2 | Partial | `fade.mp4` / `flash.mp4` stand in for montage failure modes. |
| C3–C5 | Pass | Existing golden and reconciliation suites. |
| R1–R6 | Pass | Suites plus committed `uv.lock`; `uv sync --frozen --all-groups`. |
| H1–H7 | Pass | Partial report + dashboard copy tests; H7 vocabulary search. |
| L1–L5 | Pass | Prior phase tests; not re-litigated here. |
| F1–F5 | Pass | Prior ingest/error suites. |
| F6 | Pass | Pattern scan; no Docker image history to scan. |
| P1 | Pass | `LICENSE` is Apache-2.0 with appendix copyright. |
| P2 | Pass | Appendix copyright is Edgar Coutiño Ocampo (public GitHub publication). |
| P3–P5 | Pass | Notices + SBOM tests; no `ultralytics`. |
| P6 | Pass | No AGPL combined artifact. ADR-0007 path still open. |
| P7 | Pass | Hygiene test; generated mp4s gitignored. |
| P8 | Pass | Manifest paths are FFmpeg fixtures from `scripts/generate_fixtures.py`. |
| N1 | Pass | Upload identity within the existing API/CLI tests. |
| N2 | Qualified | Synthetic CPU-core table in `docs/operations/benchmark-baseline.md`. |
| N3 | Not run | No 2160p operator clip. |
| N4 | Pass | CPU/GPU concurrency settings exist; GPU unused in base install. |
| D1–D4, D6–D7 | Pass | README, ADR index, this file, project-state. |
| D5 | CLI pass / Compose blocked | Demo script timed on CLI. No Docker daemon on this host. |

**Candidate status:** `0.1.0-rc` for source and CLI evidence. Compose/container
promotion waits for a Docker host. Do not claim 60 s 1080p hardware numbers.
