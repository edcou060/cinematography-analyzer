# Backlog (measured revisit triggers)

Items enter this list only with a trigger from an ADR, a benchmark, or
`docs/architecture/system-design.md` section 18. They are not a feature wishlist.

| Work | Trigger | Record |
| --- | --- | --- |
| Real `SubjectDetector` extra | Owner chooses one ADR-0007 path (AGPL combined work, Enterprise licence, or a permissively licensed detector) | ADR-0007 |
| Personal copyright line on `LICENSE` | Public GitHub publication under a named natural person or company | ADR-0008, checklist P2 |
| 60 s 1080p / 5 min / 2160p RTF table | Operator supplies `bench-01`–`bench-03` (self-recorded); synthetic fixtures are not a substitute | product contract §7, checklist N2/N3 |
| Shot-boundary P/R on those clips | Same corpus, 200 ms tolerance already used on golden fixtures | checklist C1/C2, S10 |
| Public original/evidence image artifact ids | Dashboard or API consumers need to fetch JPEGs without capability-UUID friction; revisit ADR-0020 | ADR-0020 |
| Prometheus scrape / OpenTelemetry | In-process JSON at `GET /metrics` is insufficient for a multi-host SLO | ADR-0022 |
| SAM 2 masks | Bounding boxes contaminate palette or motion, and a measured eval shows masks improve the target metric | system-design §18 |
| NVDEC | Decode is the dominant wall-time fraction on supported NVIDIA hardware | system-design §18 |
| Triton | Several concurrent inference clients need batching or versioned serving | system-design §18 |
| Ray | Celery cannot express required scheduling or object locality | ADR-0002, §18 |
| Kubernetes | One-host Compose no longer meets availability or scaling goals | §18 |
| Parquet timelines | JSON timeline size or query cost exceeds the response budget | §18 |
| WebSocket/SSE | Polling creates measurable latency or load | §18 |
| Camera-movement labels | Temporal validation of global vs residual motion is good enough to name pans/tilts without lying | metric-definitions, original-blueprint corrections |
| Narrative scene grouping | A separate semantic model exists; do not rename shots | ADR-0001 |
| LUFS library | PCM window features are shown to be the wrong loudness unit for a stated comparison | ADR-0016 |
| Shared-memory `FrameStore` | Artifact JPEG reads dominate after the existing cache, on a single host | ADR-0004 |
| pip-audit / container CVE gate in CI | A published image exists and Docker is available on the release host | this phase’s security notes |
