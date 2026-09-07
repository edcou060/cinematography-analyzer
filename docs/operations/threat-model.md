# Threat model

The primary threat is untrusted, complex binary media processed by native
libraries (FFmpeg, PyAV, OpenCV). Uploaders are not trusted. Filename, MIME
type, container metadata, claimed duration, and codec tags are attacker
controlled.

## Assets

- Canonical original media and sample JPEGs under `artifact_root`.
- PostgreSQL job and report metadata.
- Worker processes and their memory.
- Operator logs and metrics (must not become a leak channel).

## Entry points

- `POST /v1/videos` streamed upload.
- `POST /v1/analyses` and cancel.
- `GET /v1/artifacts/{id}` capability URL.
- CLI ingest/analyze of a local path (operator-trusted host, still untrusted bytes).
- Celery JSON commands (identifiers only; Redis is transport).

## Controls

### Upload

- Stream in bounded chunks. Never `await file.read()` of the whole body.
- Enforce hashed `LimitsConfig` (bytes, duration, dimensions) plus codec,
  stream-count, rotation, and SDR transfer rules at probe time.
- Generated storage names. Original filename is sanitized metadata only.
- In-flight analysis quota at the API. Disk headroom before ingest.

### Subprocess

- Argument arrays, `shell=False`, wall timeout, process-group kill, bounded
  stdout/stderr.
- Unix child rlimits (open files, processes, address space) when the platform
  supports them.
- No input URLs. Only uploaded or local artifact paths constructed by this
  process.

### Artifacts and API

- Originals live under `canonical/`, not a static web root.
- Artifact GET authorizes by server-issued UUID.
- `canonical_path` rejects traversal, NUL, backslash, and keys that escape the
  canonical tree.
- Cleanup may touch `tmp` and `quarantine` only, or a resolved canonical key.
- SafeError and structured logs omit host paths, raw filenames, and stderr.

### Supply chain

- Committed `uv.lock`. Base-install licence check and `THIRD_PARTY_NOTICES.md`.
- Ultralytics is gated out of the resolution (ADR-0007).
- Weights identity is checked on GPU worker readiness; the fake detector uses a
  declared digest, not a silent download.

## Residual risk

Native parsers can still fault. Isolation is timeout, rlimit, and process
boundaries, not a sandbox hypervisor. Quota checks are not a distributed lock.
A client who holds an artifact UUID can fetch that blob; treat the id as a
capability.
