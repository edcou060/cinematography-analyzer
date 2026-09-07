# Phase 09 - Evidence-first dashboard

## Mission

Build a polished Streamlit/Plotly client that uses only the HTTP API and makes the analysis inspectable. This is the portfolio-facing product layer, not a second backend.

## Context budget

Read only:

- `docs/project-state.md`
- dashboard/API ADRs
- `docs/architecture/system-design.md` sections 6 and 12
- `docs/metrics/metric-definitions.md` sections 1, 8-10
- OpenAPI/report schema and API client package
- this phase guide

## Deliverables

- Typed API client isolated from Streamlit page code.
- Upload/start/status flow with retry and readable failure states.
- Overview page: video, job state, shot timeline, ASL distribution, availability.
- Shot inspector: evidence frame, boundary/time, palette, L-star distribution, composition overlay, metric provenance/warnings.
- Tension timeline with visible cut/audio/motion components and shot boundaries.
- Graceful layouts for no person, no audio, optional-stage failure, and critic disabled.
- UI tests for transformations/client behavior plus a manual visual QA checklist.

## UX contract

The interface must distinguish measured, estimated, and interpreted values. It must never call thirds proximity a score of “good composition,” never call detected shots narrative scenes, and never show the tension proxy without its components/caveat.

## Steps

1. Create an HTTP client with typed response validation, timeouts, and safe retry only for idempotent reads.
2. Stream upload through the API and persist only IDs in session state.
3. Poll status with backoff or use the documented event path; stop polling terminal jobs.
4. Render progressive stage availability rather than fake percentage animation.
5. Create overview charts with bounded data and consistent millisecond-to-timecode conversion.
6. Synchronize selected timeline point/shot with video seek as far as Streamlit supports reliably. If true continuous bidirectional sync is fragile, implement click-to-seek/shot selection and document the limitation.
7. Render palette widths from proportions and show exact hex values.
8. Render L-star histogram/percentiles and lighting-rule evidence.
9. Render subject overlay with thirds/center guides and confidence/coverage.
10. Render tension proxy plus component traces; tooltip names method/version.
11. Add empty/error/partial/loading states and accessible labels/color contrast.
12. Test API client/data transforms; manually inspect common viewport sizes and every degradation fixture.

## Required verification

```bash
uv run pytest tests/unit/dashboard tests/integration/dashboard_client -q
uv run ruff check apps src tests
uv run ruff format --check apps src tests
uv run mypy src apps
uv run streamlit run apps/dashboard/app.py
```

Manual QA must cover: successful analysis, no audio, no subject, spatial unavailable, corrupt upload, canceled job, very short shot, many-shot timeline, and long hex/name wrapping.

## Exit gate

- [ ] Dashboard has no DB credentials or worker imports.
- [ ] Every visible metric can reveal evidence/provenance.
- [ ] Degraded reports remain navigable.
- [ ] Timeline requests are windowed/bounded.
- [ ] Video/timeline synchronization limitations are honest.
- [ ] Text avoids artistic-quality claims.
- [ ] Visual QA checklist is completed with screenshots for the README.
- [ ] `docs/project-state.md` points to Phase 10.
