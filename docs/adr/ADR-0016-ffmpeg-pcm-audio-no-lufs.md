# ADR-0016: FFmpeg PCM audio extraction without a LUFS library

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

Phase 07 needs windowed audio features (RMS/dBFS, onset strength, spectral flux) and a
valid no-audio result. Short-term LUFS is optional in the metric definitions and
requires a named, tested loudness library. Adding librosa or pyloudnorm for one unused
field would expand the dependency surface without a review.

`AudioConfig` already hashes `sample_rate_hz` (22050). Window length changes the
features; if it is not hashed, two configs could share an analysis identity.

## Decision

Extract a mono s16le PCM stream with FFmpeg (`-vn -ac 1 -ar {sample_rate_hz} -f s16le`)
through an argument array, wall-time timeout, and stdout byte cap. Do not add a
loudness library. `AudioWindowValue.loudness_lufs_short_term` stays `None`.

`AudioConfig` gains hashed `window_ms` default 1000. Timeline hop lives on
`TensionConfig` (ADR-0017) so audio/motion/cut share one integer-millisecond grid.
Audio `method_version` is `audio-v1`.

No audio stream is `MetricStatus.NO_AUDIO` with reason `no_audio_stream`, not silence
and not `FAILED`. FFmpeg is not invoked when `video.has_audio` is false. Extract
failures degrade the audio pillar to `UNAVAILABLE` with a reason; they do not fail the
report.

## Alternatives considered

**Add pyloudnorm or librosa for LUFS.** Rejected for this phase: extra native/scientific
dependency without a reviewed implementation card.

**Share hop_ms on AudioConfig only.** Rejected: cut activity and motion resampling need
the same grid; hop belongs with the tension timeline.

## Consequences

Easier: no-audio clips succeed; LUFS absence is explicit; window length is part of
identity.

Harder: short-term loudness remains unavailable until a later ADR names a library and
bumps `audio-v1`. Default config hash snapshots change (with ADR-0015 and ADR-0017).

## Verification

Unit tests cover missing stream, missing binary, timeout, oversized stdout, and
odd-length PCM. Golden `no_audio.mp4` reports audio `UNAVAILABLE` / `no_audio_stream`.
A variant that only changes `audio.window_ms` must hash differently.

## Revisit trigger

A reviewed loudness library is added; then set LUFS, hash its parameters, and bump
`audio-v1`.
