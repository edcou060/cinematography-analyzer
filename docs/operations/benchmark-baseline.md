# Benchmark baseline

Recorded 2026-09-07 from `docs/examples/release-benchmark.json` (copy of
`build/release-benchmark.json`). Do not invent hardware numbers. The 60-second
1080p, 5-minute, and 2160p clips in the product contract are operator-supplied
and were not present. This table is the CPU-core synthetic corpus only.

## Harness

```bash
make fixtures
mkdir -p build
uv run cine-analyzer benchmark --manifest fixtures/benchmark/manifest.yaml --output build/release-benchmark.json --profile
uv run cine-analyzer validate-benchmark build/release-benchmark.json
```

The committed manifest is JSON (a YAML subset) so the base install does not
take PyYAML. Clips are the tiny generated fixtures under `fixtures/video/`.

## Default identity (must not change)

- `pipeline_version`: `0.1.0`
- default config hash:
  `66dced8dd50901cdfea31549d1395668fcca7bbc425288c3b705fe342d6304b7`
- `commit` field in this run: `uncommitted` (historical; recorded before the
  first commit. Not the tag and not current `main`.)
- hardware: `macOS-13.5-arm64-arm-64bit python=3.12.7`
- profile: `cpu_core`, JPEG cache `on`

## Optimization chosen

Per-report JPEG byte cache in `load_decoded_jpegs` (`contextvars`). Chromatic,
spatial, and motion stages previously each called `store.local_path(key).read_bytes()`
for overlapping sample keys. A `cProfile` pass of the report stage ranked
`_measure_chromatic` / `_palette` / `_fit_kmeans` at the top of wall time; the
cache is the one change landed. It is not hashed configuration.

`profile_top` from this run (first names): `_run_clip`, `_timed_report`,
`execute`, `_measure_chromatic`, `analyze_shot`, `_palette`, `_fit_kmeans`,
`load_sklearn`.

## Results

`ru_maxrss` on this OS is bytes. Cold then warm runs reuse content-hash
identity. `validate-benchmark` returned `benchmark report ok`. Golden status:
pass on every executed clip.

RTF milli is `wall_ms * 1000 / duration_ms` (1000 ≈ real-time).

| Clip | Duration ms | Cold wall_ms | Cold RTF milli | Warm wall_ms | Warm RTF milli | jpeg_reads | jpeg_hits | Peak RSS (warm, MiB) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| two_color_cut | 4000 | 1552 | 388 | 612 | 153 | 2 | 36 | 131 |
| no_cut | 4000 | 469 | 117 | 468 | 117 | 1 | 34 | 136 |
| no_audio | 1000 | 127 | 127 | 120 | 120 | 1 | 11 | 136 |
| tension_signals | 4000 | 5372 | 1343 | 1010 | 252 | 15 | 23 | 279 |

Peak RSS rose from 131 MiB (`two_color_cut` cold) to 279 MiB after
`tension_signals`.

Before/after for the cache (unit count of `local_path` on one shared key used
by chromatic, composition, and motion purposes):

| Condition | `local_path` calls for one shared key |
| --- | --- |
| Cache off (no `jpeg_read_cache` context) | 3 |
| Cache on (report stage) | 1 |

## Shot-boundary golden (200 ms tolerance)

From `tests/golden/shots/expected.json`, not from operator `bench-01`–`bench-03`.

| Clip | Expected internal boundaries (ms) | Strict | Outcome |
| --- | --- | --- | --- |
| two_color_cut | 2000 | yes | precision 1.0, recall 1.0 |
| no_cut | (none) | yes | precision 1.0, recall 1.0 |
| fade | (none) | no | dissolve not reported as a hard cut |
| flash | 2000, 2080 | no | known false cuts; published, not hidden |

## Caveats

Tiny fixtures are not a substitute for a 60s 1080p clip. RTF on synthetic
solids will not predict detector-on-CPU cost. `ru_maxrss` units differ on
macOS (bytes) and Linux (kilobytes); compare only within one OS. Checklist
N3 (2160p `bench-03`) was not executed.
