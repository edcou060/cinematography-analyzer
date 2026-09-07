# Operations runbook

Inspect logs for `request_id` / `trace_id` / `analysis_id` / `stage`. Metrics
are `GET /metrics` JSON. IDs are never Prometheus labels.

Retry guidance follows `docs/contracts/data-contracts.md` prefixes.

## MEDIA_TOO_LARGE / MEDIA_EMPTY / MEDIA_UNREADABLE

1. Symptom: upload rejected; HTTP 413 for too large, 400 otherwise.
2. Code: `MEDIA_*` as returned.
3. Logs/metrics: `upload_rejections_total{reason}`; no filename in the error.
4. Cause: body over hashed limit, zero bytes, or unreadable source.
5. Diagnostics: confirm `LimitsConfig.max_upload_bytes`; do not cat the file
   in shared logs.
6. Recovery: client resubmits a smaller or intact file.
7. Retry: no.
8. Integrity: quarantine file is deleted after the handler returns.
9. Escalate: repeated 413s from one client may be quota abuse.

## MEDIA_CORRUPT / MEDIA_UNSUPPORTED_* / stream and dimension codes

1. Symptom: ingest fails after probe; HTTP 400.
2. Code: `MEDIA_CORRUPT`, `MEDIA_UNSUPPORTED_CODEC`,
   `MEDIA_UNSUPPORTED_TRANSFER`, `MEDIA_VIDEO_STREAM_COUNT`,
   `MEDIA_AUDIO_STREAM_COUNT`, `MEDIA_DIMENSIONS_*`, `MEDIA_DURATION_*`,
   `MEDIA_UNSUPPORTED_ROTATION`, `MEDIA_FRAME_RATE_UNKNOWN`,
   `MEDIA_UNEXPECTED_STREAM`, `MEDIA_AUDIO_INCONSISTENT`.
3. Logs: `ingest` stage, `error_code`; `upload_rejections_total`.
4. Cause: hostile or out-of-scope media (HDR, extra streams, unknown codec).
5. Diagnostics: re-run `cine-analyzer doctor`; do not paste ffprobe stderr
   into tickets.
6. Recovery: reject. Do not transcode in-place as a hidden path.
7. Retry: no.
8. Integrity: staging aborted.
9. Escalate: a newly common codec may justify an ADR, not a silent allow.

## PROBE_TIMEOUT / PROBE_UNAVAILABLE / PROBE_FAILED

1. Symptom: ingest fails; retryable.
2. Code: `PROBE_TIMEOUT`, `PROBE_UNAVAILABLE`, `PROBE_FAILED`.
3. Metrics: `stage_runs_total` is ingest-adjacent; logs `span=compute` unused.
4. Cause: ffprobe missing, hung parser, or killed by timeout/rlimit.
5. Diagnostics: `cine-analyzer doctor`; worker RSS; timeout settings.
6. Recovery: restore ffprobe; increase timeout only with an ADR-aware config
   hash change if the hashed analysis limits are not involved (timeout is
   deployment settings).
7. Retry: yes, bounded.
8. Integrity: no canonical blob committed.
9. Escalate: timeouts on tiny fixtures mean a stuck native parser.

## SHOT_* / extract failures

1. Symptom: sampling stage retries then fails the analysis.
2. Code: `SHOT_FAILED`, `SHOT_DECODE_FAILED`, `SHOT_UNAVAILABLE`,
   `SHOT_EXTRACT_*`, `SHOT_UNSUPPORTED_*`.
3. Metrics: `stage_runs_total{stage=sampling,error_class=SHOT}`.
4. Cause: detector/backend mismatch or decode miss at a requested timestamp.
5. Diagnostics: sampling manifest `UNAVAILABLE` reasons; not silent substitution.
6. Recovery: retry once for extract transients; terminal for unsupported detector.
7. Retry: bounded for extract; no for unsupported backend.
8. Integrity: missing frame stays unavailable; later pillars degrade.
9. Escalate: systematic UNAVAILABLE on valid fixtures.

## ARTIFACT_* 

1. Symptom: stage fails or GET 404.
2. Code: `ARTIFACT_MISSING`, `ARTIFACT_INVALID_KEY`, `ARTIFACT_WRITE`,
   `ARTIFACT_PROMOTE`, `ARTIFACT_STAGING_CLOSED`, `ARTIFACT_CHECKSUM_MISMATCH`.
3. Metrics: `artifact_failures_total{operation}`.
4. Cause: lost blob, traversal attempt, disk error, or checksum clash.
5. Diagnostics: `canonical_path` refusal; never log the resolved host path.
6. Recovery: checksum mismatch is terminal; write/promote may retry.
7. Retry: write/promote yes; invalid key and checksum no.
8. Integrity: existing canonical bytes are left untouched on mismatch.
9. Escalate: promote loops with free disk.

## MODEL_UNAVAILABLE

1. Symptom: GPU worker will not take work; CPU fake path still measures.
2. Code: `MODEL_UNAVAILABLE`.
3. Health: `cine-analyzer worker-ready --role gpu` is unavailable.
4. Cause: ultralytics extra missing, backend `none`, weights digest mismatch,
   or init skipped.
5. Diagnostics: `CINE_SPATIAL_WORKER_BACKEND`, `CINE_SPATIAL_WEIGHTS_SHA256`.
6. Recovery: fix settings; restart the GPU process so init runs once.
7. Retry: no until identity is corrected.
8. Integrity: no partial GPU writes.
9. Escalate: ADR-0007 still blocks a real detector extra.

## RESOURCE_LIMIT (in-flight quota)

1. Symptom: `POST /v1/analyses` HTTP 429.
2. Code: `RESOURCE_LIMIT`.
3. Metrics: `analysis_active_jobs` at or above `CINE_MAX_INFLIGHT_ANALYSES`.
4. Cause: too many QUEUED/RUNNING/CANCEL_REQUESTED rows.
5. Diagnostics: `GET /metrics`; list non-terminal analyses in PostgreSQL.
6. Recovery: wait for completion or cancel stale jobs; scale workers.
7. Retry: yes, after backoff.
8. Integrity: no new identity inserted.
9. Escalate: quota too low for the demo corpus.

## RESOURCE_DISK

1. Symptom: ingest refused before probe.
2. Code: `RESOURCE_DISK`.
3. Cause: free bytes below `CINE_MIN_FREE_BYTES`.
4. Diagnostics: host `df`; cleanup `tmp`/`quarantine`.
5. Recovery: `cine-analyzer cleanup --prefix tmp`; free volume space.
6. Retry: yes after space returns.
7. Integrity: no partial canonical original.
8. Escalate: volume too small for the 60s 1080p operator clip.

## RESOURCE_STATE / RESOURCE_NOT_READY

1. Symptom: HTTP 503 or 409 (report not ready).
2. Code: `RESOURCE_STATE`, `RESOURCE_NOT_READY`.
3. Health: `/health/ready` 503 if PostgreSQL (or Redis in Celery profile) fails.
4. Cause: DB down, API restart, worker lease loss, report not aggregated.
5. Diagnostics: `/health/live` vs `/health/ready`; `span.closed` queue_wait vs
   compute; Celery broker ping.
6. Recovery: restore Postgres/Redis; poll status; do not re-upload on 409.
7. Retry: 409 poll; 503 bounded.
8. Integrity: leases compare-and-set; stale success cannot overwrite.
9. Escalate: ready flapping after Redis restart — redeliver is expected;
   PostgreSQL remains truth (ADR-0003).

## SCHEMA_INVALID

1. Symptom: HTTP 422 or CLI validation failure.
2. Code: `SCHEMA_INVALID`.
3. Cause: bad JSON, window bounds, or corrupt report artifact.
4. Recovery: fix the client request; do not repair reports in place.
5. Retry: no.
6. Integrity: aggregation marks FAILED if the report JSON does not validate.

## CANCELED_BY_CLIENT

1. Symptom: analysis state `CANCELED`.
2. Code: `CANCELED_BY_CLIENT`.
3. Cause: cancel during a chunk or between stages.
4. Recovery: none; submit a new analysis if work should continue.
5. Retry: no.
6. Integrity: in-flight attempts move to CANCELED; no silent continue.

## Critic unavailable

Optional. Disabled unless `critic.enabled` is true and `CINE_CRITIC_BACKEND` is
`fake` or `openai`. Timeout, audit rejection, or a missing model server stores an
omitted critique (`FAILED` / `NOT_COMPUTED`) in `critique_runs`. Analysis state
and the report artifact are unchanged (ADR-0005, ADR-0023). CPU workers also
listen on the `critic` queue so a third process is not required.

## Redis restart

Celery redelivers JSON commands. Workers lease in PostgreSQL. Duplicate
storage keys are not created. Expect `/health/ready` 503 until Redis answers
when `CINE_EXECUTION_BACKEND=celery`.

## API restart while jobs run

In-flight HTTP uploads abort. Already queued analyses continue in workers.
Clients poll `/v1/analyses/{id}` with the same id.

## Worker dies after writing output and before commit

Retry reuses or safely replaces the canonical key. Checksum mismatch is
terminal. Covered by Celery equivalence tests and the failure-drill suite.
