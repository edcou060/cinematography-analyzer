# Limitations (release candidate 0.1.0)

These are product facts, not temporary embarrassments.

## Input

- SDR only. HDR / PQ / HLG is rejected with a named reason.
- One video stream; zero or one audio stream. No remote URLs, live capture, or
  image sequences.
- Ceilings: 1 GiB, 20 minutes, 4096×2160. Acceptance is an `ffprobe` result,
  never an extension or MIME type.

## Measurement vs estimate vs interpretation

- Shot boundaries come from the pinned PySceneDetect adaptive detector.
  Dissolves are often missed (`fade.mp4`). Flash frames can produce false cuts
  (`flash.mp4` at 2000 ms and 2080 ms, 200 ms golden window).
- Lighting-key and framing labels are thresholded estimates. Framing abstains
  without a detector.
- Thirds proximity is geometry, not composition quality.
- Tension is a configurable proxy of cut, audio, and motion components, not
  audience emotion.
- The critic is optional, metrics-only, and cannot modify or fail analysis.

## Spatial / detector licence

The base install has no person detector. Spatial is `unavailable` with
`detector_not_installed` by default. Ultralytics is AGPL-3.0 or Enterprise;
combining it with this Apache-2.0 tree is an owner decision (ADR-0007), not a
dependency-file accident. No identity, face recognition, or actor labels.

## Calibration and hardware

Heuristic thresholds were not fit on a large annotated film corpus. Synthetic
FFmpeg fixtures prove formulas and golden cuts; they do not predict 60 s 1080p
detector-on-CPU cost. The 60 s / 5 min / 2160p clips in the product contract
are operator-supplied and were not present for this candidate.

## Runtime

- Python 3.12, `uv.lock`, FFmpeg/ffprobe on PATH.
- Default execution: local poll worker and PostgreSQL for the API. CLI
  ingest/analyze may use disposable SQLite.
- Celery/Redis is optional. Compose was not executed on the Phase 13 host
  (no Docker daemon).
- Observability is in-process JSON, not Prometheus.
- `ru_maxrss` units differ on macOS (bytes) and Linux (kilobytes).
