# Product contract

- Status: Accepted (Phase 00)
- Applies to: MVP, pipeline version `0.1.x`
- Authority: this document defines what a user may expect. `docs/architecture/system-design.md` defines how it is built. `docs/contracts/data-contracts.md` owns field-level schemas. Where this document and a schema disagree, the schema wins and this document is corrected by ADR.

## 1. What the product is

The Automated Cinematography Analyzer accepts one video clip, measures observable properties of its editing, colour, framing, and audio, and returns a versioned report in which every number is traceable to a frame identifier or a time range.

It is a measurement instrument with an honest error model. It is not an arbiter of artistic merit. A reviewer should be able to read a report and distinguish three different things: what was measured, what was estimated by a heuristic, and what could not be determined at all.

## 2. Normative vocabulary

These words have exactly one meaning across code, schemas, API responses, dashboard copy, and documentation. Using them loosely is a defect.

| Term | Meaning | What it is not |
| --- | --- | --- |
| **Shot boundary** | A frame index and presentation timestamp at which the pinned detector reported a visual transition. | Not a proven edit. Detectors miss dissolves and fire on flashes, pans, and hard lighting changes. |
| **Shot** | The half-open interval between two consecutive boundaries, plus the clip start and end. | Not a semantic unit. Nothing about meaning, subject, or location is implied. |
| **Narrative scene** | A semantic grouping of shots into a dramatic unit. The MVP does not infer it, does not store it, and does not display it. The word is reserved so a later feature can use it without renaming existing fields. | Never a synonym for a detected shot. |
| **Measured** | A deterministic function of decoded pixels, audio samples, or container metadata. Same input plus same config plus same code version yields the same value. Carries a unit and a method version. | Not free of sampling error. A measurement taken from three sampled frames describes those frames. |
| **Estimated** | A heuristic label derived from measured features by thresholds or rules that were calibrated on a small annotated set. Carries a confidence and the evidence that produced it. | Not ground truth, and not the filmmaker's intent. |
| **Interpreted** | Optional prose produced by a language model from an already-validated report. Stored separately, regenerable, deletable. | Never an input to any metric, and never able to change a measured or estimated value. |
| **Unavailable** | A field the system deliberately did not produce, with a machine-readable reason such as `no_audio_stream`, `detector_not_installed`, `stage_failed`, or `insufficient_samples`. | Not zero, not null-as-shorthand, not an empty list standing in for absence. |

The corresponding rule for the pipeline: a stage that cannot compute a value emits `unavailable` with a reason. Fabricating a neutral default is a defect, not a graceful degradation.

## 3. Supported input

### 3.1 Delivery

Local file upload through the API or CLI. One clip per analysis. The MVP does not fetch remote URLs, ingest camera or capture devices, accept image sequences, or analyse live streams.

### 3.2 Validation posture

Every claim attached to an upload is untrusted: filename, extension, declared MIME type, container metadata, duration, frame rate, dimensions, and codec tags. Acceptance is decided by an `ffprobe` invocation with an argument array, a timeout, and JSON output — never by the extension. A file that probes successfully but disagrees with its own metadata is rejected with a specific reason.

### 3.3 Accepted

| Property | MVP acceptance |
| --- | --- |
| Container | Whatever the pinned `ffprobe` build reports as a single coherent programme, in practice MP4, MOV, MKV, WebM. |
| Video streams | Exactly one decodable video stream. |
| Video codecs | H.264, H.265/HEVC, VP9, AV1, and MPEG-4 Part 2, subject to the probe confirming decodability. |
| Audio streams | Zero or one. Absent audio is a supported case, not an error, and marks the audio pillar `unavailable` with reason `no_audio_stream`. |
| Colour | SDR only. Rec.709 and sRGB-like transfer characteristics. |
| Frame rate | Constant or variable. Timing always derives from presentation timestamps, never from a nominal frame-rate field. |
| Rotation | Container rotation metadata is read and applied once, before any spatial measurement. |

### 3.4 Ceilings

Defaults, from `docs/architecture/system-design.md` section 14. All are configuration, and configuration is part of the hashed analysis key.

| Limit | Default | Enforced |
| --- | --- | --- |
| Upload size | 1 073 741 824 bytes (1 GiB) | While streaming the body, before the file is complete. |
| Duration | 1 200 000 ms (20 minutes) | After probe, before any analysis is enqueued. |
| Width | 4096 px | After probe. |
| Height | 2160 px | After probe. |

### 3.5 Rejected, with an explicit reason

HDR and wide-gamut transfer functions (PQ, HLG); multiple video streams; encrypted or DRM-protected media; zero-duration or unprobeable files; anything exceeding a ceiling; formats whose only decode path is a codec the pinned build lacks. Rejection is a validation response naming the failing property. It is never a silent success with empty metrics, and the message never echoes the local storage path or the user-supplied filename.

## 4. What the report contains

The report is one validated JSON document with `schema_version`, `pipeline_version`, the configuration hash, and provenance. Summaries are served from PostgreSQL; large time series, palettes, and evidence indexes are served from immutable artifacts. The API never needs the original video in memory to serve a report.

### 4.1 Always present for an accepted clip

**Source facts** — duration in ms, dimensions, codec, frame-rate rational, audio presence, `video_sha256`, and the probe record that justified acceptance.

**Shot list** — for each shot: index, start and end in integer milliseconds, duration, boundary confidence where the detector supplies one, and the detector statistics behind the boundary.

**Editing summary** — shot count, cut density per minute, and the mean, median, and spread of shot duration. Measured, with the detector and its configuration named alongside.

**Chromatic per shot** — a dominant palette of up to five colours sorted by prevalence with letterbox bars masked, perceptual lightness and contrast percentiles in stated units, and a lighting-key estimate carrying its own confidence and the features that produced it. Fewer than five palette colours is a valid answer when no more are stable.

**Evidence** — every per-shot visual metric names the frame identifiers or time range it came from, so a reviewer can open the source frames and disagree.

**Provenance** — pipeline version, per-metric method version, configuration hash, detector version, and, where a model is involved, its weight digest.

### 4.2 Present when available, `unavailable` with a reason otherwise

**Spatial** — person detections, subject tracks, a framing estimate per shot, and thirds proximity. Requires a `SubjectDetector` implementation. The base installation ships no licensed detector, so on a default install this pillar reports `unavailable` with reason `detector_not_installed`. See `docs/adr/ADR-0007-ultralytics-license-gate.md`.

**Audio** — integrated and short-term loudness, onset activity, and spectral change. Requires an audio stream.

**Motion** — global and residual motion magnitude from sampled frame pairs. Camera-movement labels are not emitted in the MVP; the underlying motion measurements are.

**Tension proxy** — a configurable weighted combination of cut activity, audio activity, and motion, published with its weights and its component values so it can be recomputed or rejected. It is a named proxy, not a claim about what an audience feels.

**Interpretation** — an optional short critique. Disabled by default (`critic.enabled: false`).

### 4.3 Partial failure

A failed stage does not fail the report. The report is served with that pillar marked `unavailable`, the failure recorded against the stage, and the remaining pillars intact.

## 5. Caveats shown to the user

These appear in the dashboard and the report, not only here.

1. Detected shots are algorithmic edit boundaries. Gradual transitions, whip pans, strobing, and abrupt lighting changes all produce known error modes.
2. Framing labels are heuristic estimates from person and face geometry. They abstain rather than guess when evidence is weak.
3. Thirds proximity is geometric distance to rule-of-thirds intersections. Centred and deliberately off-grid framing are ordinary creative choices, so a low value carries no criticism.
4. Lighting-key labels come from thresholded lightness and contrast statistics. They describe pixels, not intent, and they are affected by grading, exposure, and codec.
5. Palettes come from deterministic sampling of a subset of frames, so they describe the sampled frames rather than every frame of the shot.
6. The tension proxy is a configurable formula whose weights are visible and adjustable. Changing the weights changes the number.
7. Metrics are comparable only across analyses that share a pipeline version and configuration hash.

## 6. Success metrics

Phase 00 fixes the definitions and the targets. Each is verified in the phase named beside it, and none of them may be marked satisfied by inspection alone.

| # | Condition | Threshold | Verified in |
| --- | --- | --- | --- |
| S1 | Upload returns an accepted analysis identifier | HTTP 202 within 1 s of the body finishing, excluding client transfer time | Phase 03 |
| S2 | Job state survives restart | Killing a worker or the UI mid-analysis loses no authoritative state; the analysis resumes or reports failure | Phase 10, Phase 11 |
| S3 | Deterministic metrics are reproducible | Byte-identical measured values across two runs on the same input, config, and code version | Phase 04, Phase 05 |
| S4 | Evidence coverage | 100 % of per-shot visual metrics carry a resolvable frame identifier or time range | Phase 08 |
| S5 | Honest degradation | Every disabled or failed pillar yields `unavailable` plus a reason; zero fabricated values | Phase 08, Phase 11 |
| S6 | Report serving is bounded | A full report is served without loading the source video into application memory | Phase 08 |
| S7 | Observability | Wall time, per-stage time, peak memory, failure counts, and cache hits recorded per analysis | Phase 11 |
| S8 | Idempotency | Re-submitting an identical `(video_sha256, config, pipeline_version)` reuses the prior analysis instead of recomputing | Phase 03 |
| S9 | Throughput is stated, not guessed | A published figure for the benchmark clips on named hardware, with peak memory | Phase 13 |
| S10 | Boundary accuracy is stated with its error | Precision and recall against hand-annotated boundaries on the benchmark set, reported with the tolerance window used | Phase 04, Phase 13 |

S10 sets no numeric target in Phase 00. Publishing a target before the annotated set exists would be inventing a requirement; Phase 04 sets the target from the first measured baseline, and the number is recorded there.

## 7. Benchmark and demo inputs

### 7.1 Legal basis

Only two categories of input are ever committed to a manifest, referenced in a benchmark, or shown in the demo:

- **Self-created footage**, recorded by the project owner, who holds the rights.
- **Synthetic clips generated by FFmpeg** from built-in sources such as `testsrc2`, `smptebars`, and `sine`, produced by a committed script.

No commercially released film or television material is redistributed, committed, or published in a report, screenshot, or recording — including under a fair-use or fair-dealing argument, which is a defence rather than a licence and is not a sound basis for a public portfolio artifact. Third-party clips may be analysed privately for the owner's own calibration; their frames and derived reports stay out of the repository and out of any published material.

Media files are never committed. `.gitignore` blocks video and audio extensions at every path. The benchmark set lives outside the repository and is identified in a committed manifest by `video_sha256`, duration, dimensions, codec, and provenance, so a benchmark result is checkable even though the bytes are not distributed.

### 7.2 The three benchmark clips

| ID | Description | Exercises | Purpose |
| --- | --- | --- | --- |
| `bench-01-static-dialogue` | Self-recorded, about 60 s, 1080p, tripod, even key light, long takes and few cuts | Boundary recall on sparse cuts; palette stability on near-static frames | Baseline correctness where the right answer is easy to annotate by hand |
| `bench-02-fast-montage` | Assembled from the owner's own footage, about 30 s, 1080p, many sub-second cuts plus two dissolves and one flash frame | `min_shot_ms`, boundary precision, known dissolve and flash failure modes | Where the detector is expected to be wrong, documented rather than hidden |
| `bench-03-lowlight-handheld` | Self-recorded, about 90 s, handheld, low-key, moving subject, delivered in 1080p and 2160p variants | Lighting-key estimate, global versus residual motion, decode and downscale cost at the resolution ceiling | Throughput ceiling and heuristic robustness in the hardest lighting |

Every clip is produced in a variant with the audio stream stripped, so the `no_audio_stream` path is exercised on real input rather than only in unit tests. Synthetic FFmpeg clips supplement these as deterministic fixtures with a known ground truth: exact cut positions, exact colours, exact silence.

### 7.3 The demo story

One narrated pass over a self-recorded clip of roughly two minutes:

1. Upload the clip and receive an analysis identifier immediately.
2. Watch stage states advance while the source video is never held by the API.
3. Open the report: shot list, editing summary, per-shot palettes and lighting-key estimates, each linked to the frames that produced it.
4. Show the spatial pillar reporting `unavailable` with reason `detector_not_installed` on a default install, and explain the licence gate as a deliberate release decision.
5. Re-submit the identical clip and configuration and show the analysis being reused rather than recomputed.
6. Submit the audio-stripped variant and show the audio pillar reporting `unavailable` with reason `no_audio_stream` while every other pillar stays intact.

Steps 4 and 6 are the point of the demo. A system that admits what it does not know is the thing being demonstrated.

## 8. Change control

Changing the accepted-input set, the report's required fields, the vocabulary, or a success metric requires an ADR and an update to this document in the same change. Adding an optional output field within a major schema version does not. Renaming or removing a field does.
