# Demo script (3–5 minutes)

Timed on 2026-09-07, CPython 3.12.7, ffmpeg 9.0.1, macOS 13.5 arm64.
Compute used a clean `CINE_STATE_PATH` / `CINE_ARTIFACT_ROOT` under `/tmp`.
Clips are the FFmpeg fixtures from `make fixtures` (never private media).

Pipeline version `0.1.0`. Default config hash
`66dced8dd50901cdfea31549d1395668fcca7bbc425288c3b705fe342d6304b7`.

Wall times below are `/usr/bin/time -p real` for the CLI process, including
interpreter startup.

## 0:00–0:20 — Problem and limits

This is a measurement instrument, not an aesthetic judge. Numbers are
reproducible and tied to frames or time ranges. Heuristic labels are estimates.
Detected intervals are shots, not narrative scenes. Spatial detection is gated
out of the Apache-2.0 base install (ADR-0007). The optional critic cannot change
a metric.

## 0:20–1:10 — Upload a shareable clip

```bash
make fixtures
uv run cine-analyzer analyze fixtures/video/two_color_cut.mp4 \
  --through report --output /tmp/two.json
```

Measured: **3.95 s** cold for a 4 s 320×240 two-colour cut. The JSON names
`analysis_id` immediately after ingest; heavy work is the report stage, not the
control-plane identity. Palette evidence is `#FB0000` then `#0000FB` (or
`#0101FB` depending on chroma rounding) with a hard cut at 2000 ms.

Dashboard path (if PostgreSQL is up): upload the same fixture through Streamlit
at http://127.0.0.1:8501. The UI is an HTTP client. Click-to-seek is one-way and
whole seconds.

## 1:10–1:50 — Durable stages and resource split

Point at the stage events: ingest → sampling (`shot_count: 2`) → report.
CPU stages own chromatics and motion. Spatial is a separate pillar. The API
process never decodes the file. Compose (when Docker is available) splits
`api` and `worker-cpu`; the local poll worker is the default without Redis.

## 1:50–2:30 — One shot: evidence, palette, lightness, provenance

Open `/tmp/two.json` or the dashboard shot inspector.

- Two shots, ASL 2000 ms, 30 shots/minute on this 4 s clip.
- Chromatic `COMPLETE`; lighting-key is an estimate from L* percentiles.
- Every per-shot visual metric names sample IDs / time ranges.
- Provenance: `method_version`, `config_hash`, `code_revision: cine-analyzer-0.1.0`.

## 2:30–3:10 — Unavailable on purpose (the demonstration)

On the same default report:

- Spatial `UNAVAILABLE`, `reason_code: detector_not_installed`.
- Audio `UNAVAILABLE` (`has_audio: false` / `no_audio_stream`).
- Critic `NOT_REQUESTED`.

Re-submit:

```bash
uv run cine-analyzer analyze fixtures/video/two_color_cut.mp4 --dry-run
```

Measured: **0.44 s**, `reused: true`. Identity is
`(video_sha256, config_hash, pipeline_version)`.

Optional audio-free named fixture (same unavailable audio path):

```bash
uv run cine-analyzer analyze fixtures/video/no_audio.mp4 --through report
```

Measured: **1.01 s**.

## 3:10–3:50 — Editing distribution, tension, partial motion

```bash
uv run cine-analyzer analyze fixtures/video/tension_signals.mp4 \
  --through report --output /tmp/tension.json
```

Measured: **5.54 s**. Availability: chromatic `COMPLETE`, audio `COMPLETE`,
spatial `UNAVAILABLE`, motion **`PARTIAL`**, tension `COMPLETE`. Shot 0 has
usable Farneback magnitudes; shot 1 often has null motion on this synthetic
clip. The report stays valid. That is the graceful-failure beat.

Dashboard tension chart: cut / audio / motion components plus the emotion
caveat. Figures: `docs/images/dashboard/tension.svg`.

## 3:50–4:20 — Profiling story

`cProfile` of the CPU-core harness ranked chromatic palette / k-means work at
the top of wall time. The landed change is a per-report JPEG byte cache in
`load_decoded_jpegs` (`contextvars`). On `two_color_cut`, one shared sample key
is read once instead of three times across chromatic, composition, and motion.

| Condition | `local_path` calls for one shared key |
| --- | --- |
| Cache off | 3 |
| Cache on (report stage) | 1 |

Machine-readable run: `docs/examples/release-benchmark.json`.

## 4:20–5:00 — Tradeoffs and next trigger

Default runner is local PostgreSQL poll, not Celery. Redis is transport.
No SAM 2, Triton, Ray, Kubernetes, Prometheus, or vLLM package. Ultralytics
stays gated until the owner picks an ADR-0007 path. Next measured trigger:
operator-supplied 60 s 1080p RTF, or a permissively licensed detector that
beats `detector_not_installed` without relicensing the base install.

Optional critic (does not fail analysis):

```bash
uv run cine-analyzer critique /tmp/two.json --backend fake
```

Measured: **0.43 s**. Prose is metrics-only; no filename.

## Recovery

If a stage is `UNAVAILABLE`, read `reason_code` and
`docs/operations/runbook.md`. Do not invent zeros. If Docker is missing, the
CLI path above is the portable demo; Compose commands stay in the README and
are unverified on hosts without a daemon.
