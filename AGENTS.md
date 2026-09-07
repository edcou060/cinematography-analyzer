# Repository instructions

## Mission

Build a reproducible video-analysis system. Measurements must be inspectable, versioned, and traceable to source frames or time ranges. Film-language labels are estimates, not objective judgments.

## Working protocol

1. Work on one phase or one task packet only.
2. Before editing, read `docs/project-state.md`, the named phase guide, and only the architecture files listed by that guide.
3. Restate the requested outcome, files likely to change, tests to run, and explicit non-goals.
4. Prefer a thin vertical slice over broad scaffolding.
5. Do not change public schemas, persistence tables, metric formulas, or job states without updating their canonical document and adding an ADR.
6. Run the phase checks. Do not claim success from code inspection alone.
7. End by updating `docs/project-state.md` to no more than 120 lines.
8. Stop after the phase exit gate. Do not begin the next phase automatically.

## Engineering constraints

- Python 3.12 is the baseline runtime unless an ADR changes it.
- Use `uv` for environments and a committed lockfile.
- Use `src/` layout and absolute package imports.
- Pydantic boundary models use `ConfigDict(extra="forbid")`.
- Persist time as integer milliseconds. Convert to seconds only at presentation boundaries.
- Queue messages contain identifiers and small JSON metadata, never images, NumPy arrays, model objects, or whole reports.
- PostgreSQL is authoritative production state. Redis is transport/cache, never authoritative job state.
- Artifacts are immutable and content-addressed where practical.
- Each stage is idempotent by `(video_sha256, config_hash, pipeline_version, stage_name)`.
- CPU and GPU concurrency limits are independent and configurable.
- Heavy models initialize once per dedicated worker process, not per request.
- The API accepts work, reports status, and serves results; it does not execute heavy analysis in web workers.
- Streamlit consumes the API. It does not import pipeline internals or write directly to the database.
- The AI critic is optional and cannot modify measured metrics.

## Quality gates

Every changed Python module must pass the applicable subset of:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

Tests must cover failure behavior, not only the happy path. Fix root causes; do not weaken assertions, suppress type errors broadly, or skip tests without an explicit documented reason.

## Safety and data handling

- Treat every upload as hostile.
- Do not trust extensions, MIME types, metadata, filenames, frame rate, duration, dimensions, or codec claims.
- Store uploads under generated identifiers outside any served static directory.
- Invoke FFmpeg/ffprobe with argument arrays, timeouts, resource limits, and no shell interpolation.
- Redact local paths and user-supplied filenames from externally visible errors.
- Never commit videos, extracted frames, model weights, secrets, generated reports, or local databases.

## Metric language

Use these terms precisely:

- **Shot boundary**: an algorithmically detected edit boundary.
- **Shot**: the interval between two boundaries.
- **Narrative scene**: not inferred in the MVP.
- **Thirds proximity**: geometric proximity to rule-of-thirds intersections; not composition quality.
- **Framing estimate**: heuristic shot-size label; not ground truth.
- **Lighting-key estimate**: thresholded lightness/contrast features; not artistic intent.
- **Tension proxy**: a configurable combination of observable components; not audience emotion.

## Change discipline

- Preserve existing behavior unless the task explicitly changes it.
- Keep commits phase-sized and reviewable.
- Add dependencies only when used in the current phase.
- Avoid speculative abstractions except the documented ports between domain logic and infrastructure.
- No premature SAM 2, Triton, Kubernetes, Ray, NVDEC, or vLLM work.
