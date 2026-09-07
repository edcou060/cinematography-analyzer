# Dashboard visual QA

Manual checklist for the Streamlit client (`apps/dashboard/app.py`). The dashboard
talks only to the HTTP API (ADR-0020). Session state stores identifiers and a
whole-second seek offset, never frames.

Play the local upload. Click-to-seek is one-way: Streamlit does not report the
playhead back to Python, and `st.video` seek is truncated to whole seconds.

## How to run

Terminal 1: `CINE_DATABASE_URL=… make migrate && make run-api`  
Terminal 2: `CINE_DATABASE_URL=… make run-worker-cpu`  
Terminal 3: `make run-dashboard` then open http://127.0.0.1:8501

Use `make fixtures` for the clips named below.

## Cases

| Case | Fixture / action | What to look for |
| --- | --- | --- |
| Successful analysis | `two_color_cut.mp4` | Overview shows measured source, detected shot intervals, ASL histogram. Shot inspector shows palette hex + widths, L* percentiles, provenance. Kind column uses Measured / Estimated / Interpreted / Unavailable. |
| No audio | clip without an audio stream (`two_color_cut.mp4`) | Audio pillar Unavailable with the supported-case caption (`NO_AUDIO` / `no_audio_stream`), not “silence”. Other pillars stay navigable. |
| No subject | default spatial backend `none` | Shot inspector schematic says “no person / spatial unavailable”. Caption names `detector_not_installed`. Thirds/centre guides still render. |
| Spatial unavailable | same as no subject, or a `PARTIAL` job | Composition overlay remains a schematic, never a “good composition” score. |
| Corrupt upload | truncated / non-media bytes | SafeError panel. No local path or filename in the error. |
| Canceled job | Cancel while `QUEUED`/`RUNNING` | Terminal Canceled. No report tabs. Status stops polling. |
| Very short shot | golden flash / sub-200 ms interval | Inspector still shows time range, provenance, and evidence ids. |
| Many-shot timeline | dense cut fixture or the many-shot SVG | Shot bar row stays on one axis; labels do not imply narrative scenes. |
| Long hex / name wrap | 64-char `content_sha256` and config hash | Identifiers wrap in the overview caption and palette hex list; nothing overflows the sidebar. |

## Honest language

- Detected shots are edit boundaries, not narrative scenes.
- Framing and lighting-key labels are estimates.
- Thirds proximity is geometric, not a quality score.
- Tension proxy is shown with cut / audio / motion components and the emotion caveat.

## README figures

Generated from `cine_analyzer.dashboard.svg` (same geometry as the UI):

- `docs/images/dashboard/palette.svg`
- `docs/images/dashboard/shot-timeline.svg`
- `docs/images/dashboard/many-shots.svg`
- `docs/images/dashboard/tension.svg`
- `docs/images/dashboard/composition.svg`
- `docs/images/dashboard/composition-empty.svg`
- `docs/images/dashboard/hash-wrap.svg`
