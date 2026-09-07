# ADR-0020: Streamlit dashboard is an HTTP client with click-to-seek

- Status: Accepted
- Date: 2026-09-06
- Owners: project owner
- Supersedes: none

## Context

Phase 09 adds the portfolio-facing UI. System design §6 already forbids database
credentials and worker imports in Streamlit. The report names sample IDs and
summary geometry; it does not expose the original-media artifact id or per-sample
JPEG artifact ids. Continuous bidirectional video/timeline sync is fragile in
Streamlit because `st.video` does not report the playhead back to Python.

## Decision

The dashboard talks only to the public HTTP API through a typed client in
`cine_analyzer.dashboard`. Session state stores identifiers and seek offsets,
never frame arrays. Timeline fetches always send `start_ms`, `end_ms`, and
`max_points`, with a UI cap of 500 (the API cap remains 2000).

Video playback uses the file still held by Streamlit's uploader widget. Clicking
a shot or timeline point sets `st.video(..., start_time=)` to that instant
truncated to whole seconds. There is no reverse sync from the playhead. If the
uploader is empty, the UI shows evidence identifiers and schematic composition
guides instead of pretending to stream the stored original.

Composition overlay is a schematic: thirds and centre guides plus a rectangle
sized from shot-median coverage/height when spatial values exist. It is not a
detector box on a real frame, because `SpatialValue` does not carry per-frame
boxes or overlay artifact ids.

httpx is a base-install dependency because the typed client lives in the library.
Streamlit and Plotly are a `dashboard` dependency group so API/worker images do
not install a browser UI stack.

## Alternatives considered

**Add original-artifact and sample-image ids to public schemas.** Deferred. That
is a contract change; the dashboard can be honest without it.

**Poll the artifact store by storage key.** Rejected: keys are not a public
capability, and possession of a server UUID is the artifact auth model.

**Bidirectional JS playhead sync.** Rejected for the MVP: extra custom
components, and Streamlit reruns would fight the player.

## Consequences

Easier: the UI cannot bypass the API or leak worker internals. Degraded reports
stay navigable.

Harder: opening an analysis id without a local upload cannot play the source
clip. Seek resolution is whole seconds.

## Verification

Import isolation: `apps/dashboard/app.py` and `cine_analyzer.dashboard` do not
load OpenCV, PyAV, PySceneDetect, SQLAlchemy engines, or worker modules. Client
tests cover SafeError mapping and GET-only retries. Visual QA checklist in
`docs/dashboard/visual-qa.md`.

## Revisit trigger

A public field for original and evidence image artifact ids, or a Streamlit
release that reports playhead position without a custom component.
