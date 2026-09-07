# ADR-0009: Ordered sample extraction uses PyAV

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

Phase 04 must extract evidence frames at planned timestamps and record both the requested and actual decoded presentation times. FFmpeg is already the probe/fixture process. Seeking independently with `ffmpeg -ss` can snap to codec keyframes or repeatedly decode from the previous keyframe. The sampling architecture asks for one ordered extraction pass.

PySceneDetect remains the shot-boundary detector. That library decodes through OpenCV (or an optional PyAV video backend) for detection only. Mixing that decode with evidence extraction would couple two stages and make requested-vs-decoded timestamps harder to test.

## Decision

Sample extraction uses PyAV (`av`) to decode the stored original in presentation order and capture the first frame whose timestamp is at or after each request, without leaving the requested shot. FFmpeg/ffprobe stay the probe and fixture tools. Shot detection stays on the PySceneDetect adapter.

Timestamps are converted to integer milliseconds once, with the same round-half-up rule as ingest.

## Alternatives considered

**FFmpeg `select` / per-timestamp `-ss`.** Rejected as the baseline: argument-array invocation is already proven, but mapping each request to an actual PTS is clumsier than reading PyAV packet timestamps, and independent seeks are the path the architecture warns against.

**OpenCV `VideoCapture` for extraction.** Rejected: seeking and timestamp authority are weaker than PyAV, and it would put evidence extraction on the same stack as detection without a PTS-first API.

**One combined detect-and-extract pass.** Rejected: sampling is a separate stage after a validated `ShotSet`. Coupling them would make short-shot merging and cross-shot rejection harder to unit-test.

## Consequences

Easier: ordered decode, first-class presentation timestamps, and a clear port (`SampleExtractor`) with a fake for tests.

Harder: two decode libraries in the base install (OpenCV via PySceneDetect, PyAV for extraction). Operators still supply FFmpeg for probe/fixtures.

Irreversible in practice: changing the extractor changes `decoded_ms` and evidence checksums, so it is a method-version bump.

## Verification

Unit tests feed synthetic timestamps into the extractor port. Integration tests decode generated fixtures and assert `requested_ms` and `decoded_ms` are both stored, and that a frame whose PTS falls outside the requested shot is `UNAVAILABLE` rather than substituted.

## Revisit trigger

Measured extraction wall time is dominated by full-file sequential decode on accepted clip sizes, and a benchmark shows a keyframe-aware or GPU path improving RTF without changing `decoded_ms` policy.
