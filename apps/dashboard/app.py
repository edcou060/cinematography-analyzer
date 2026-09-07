"""Evidence-first Streamlit client. HTTP only (ADR-0020)."""

import time
from io import BytesIO
from typing import Protocol
from uuid import UUID

import plotly.graph_objects as go
import streamlit as st

from cine_analyzer.dashboard.client import AnalyzerClient, DashboardClientError
from cine_analyzer.dashboard.copy import (
    PAGE_TITLE,
    SYNC_LIMITATION,
    caveats_markdown,
    critic_caption,
    empty_upload,
    evidence_chip_caption,
    failed_job,
    interpretation_label,
    lighting_caption,
    no_audio,
    no_subject,
    palette_caption,
    progress_caption,
    spatial_caption,
    state_caption,
    tension_caption,
)
from cine_analyzer.dashboard.svg import composition_svg, palette_svg
from cine_analyzer.dashboard.transforms import (
    ShotBar,
    evidence_chips,
    format_timecode,
    is_terminal_status,
    kind_for_metric_status,
    lightness_markers,
    palette_bars,
    pillar_rows,
    poll_delay_ms,
    seek_seconds,
    shot_bars,
    shot_duration_histogram,
    tension_series,
    timeline_query,
)
from cine_analyzer.domain.critic import CriticInput
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import AnalysisReport, Critique, ShotAnalysis
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.settings import load_settings

_SESSION_VIDEO = "video_id"
_SESSION_ANALYSIS = "analysis_id"
_SESSION_SHOT = "selected_shot_id"
_SESSION_SEEK = "seek_s"
_SESSION_POLL = "poll_attempt"
_SESSION_ERROR = "last_error"
_SESSION_BYTES = "_upload_bytes"
_UI_FONT = "Helvetica, Arial, sans-serif"
_THEME_CSS = """
<style>
html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"],
[data-testid="stSidebar"], [data-testid="stMarkdownContainer"],
.stMarkdown, .stCaption, label, p, h1, h2, h3, h4 {
  font-family: Helvetica, Arial, sans-serif !important;
}
code, pre, [data-testid="stCode"], .stCode {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
}
footer { visibility: hidden; }
[data-testid="stToolbar"],
[data-testid="stAppDeployButton"],
.stAppDeployButton {
  display: none !important;
}
</style>
"""
_CHART_FONT = {"family": _UI_FONT, "color": "#111111"}


def _apply_theme() -> None:
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


class _UploadedFile(Protocol):
    name: str

    def getvalue(self) -> bytes: ...


@st.cache_resource
def _cached_client(url: str) -> AnalyzerClient:
    """One HTTP client per API base URL for the Streamlit process."""
    return AnalyzerClient(url)


def _client() -> AnalyzerClient:
    return _cached_client(load_settings().api_public_url)


def _set_error(message: str) -> None:
    st.session_state[_SESSION_ERROR] = message


def _clear_error() -> None:
    st.session_state[_SESSION_ERROR] = None


def _maybe_seek(ms: int) -> None:
    """Apply click-to-seek once, then skip if the offset did not change."""
    seconds = seek_seconds(ms)
    if int(st.session_state[_SESSION_SEEK]) == seconds:
        return
    st.session_state[_SESSION_SEEK] = seconds
    st.rerun()


def _selection_points(event: object) -> list[object]:
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    points = getattr(selection, "points", None) if selection is not None else None
    if points is None and isinstance(selection, dict):
        points = selection.get("points")
    if not points:
        return []
    return list(points)


def main() -> None:
    """Page entry. Streamlit reruns this function on every interaction."""
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    _apply_theme()
    st.title(PAGE_TITLE)
    st.caption(
        "Measured values carry units and method versions. Estimated labels can abstain. "
        "Interpreted prose is optional and cannot change a metric."
    )
    for key, default in (
        (_SESSION_VIDEO, None),
        (_SESSION_ANALYSIS, None),
        (_SESSION_SHOT, None),
        (_SESSION_SEEK, 0),
        (_SESSION_POLL, 0),
        (_SESSION_ERROR, None),
        (_SESSION_BYTES, None),
    ):
        st.session_state.setdefault(key, default)

    client = _client()
    _sidebar(client)
    uploaded = st.session_state.get(_SESSION_BYTES)
    if uploaded is not None:
        st.video(uploaded, start_time=int(st.session_state[_SESSION_SEEK]))
        st.caption(SYNC_LIMITATION)
    else:
        st.info(empty_upload())

    if st.session_state.get(_SESSION_ERROR):
        st.error(failed_job(str(st.session_state[_SESSION_ERROR])))

    analysis_id = st.session_state[_SESSION_ANALYSIS]
    if analysis_id is None:
        return
    _analysis_body(client, UUID(str(analysis_id)))


def _sidebar(client: AnalyzerClient) -> None:
    st.sidebar.header("Analysis")
    st.sidebar.caption(f"API `{load_settings().api_public_url}`")
    uploaded = st.sidebar.file_uploader("Clip", type=["mp4", "mov", "mkv", "webm"])
    start = st.sidebar.button("Upload and start", type="primary", disabled=uploaded is None)
    if start and uploaded is not None:
        _start(client, uploaded)
    if st.sidebar.button("Cancel", disabled=st.session_state[_SESSION_ANALYSIS] is None):
        _cancel(client)
    st.sidebar.markdown("### Caveats")
    st.sidebar.markdown(caveats_markdown())


def _start(client: AnalyzerClient, uploaded: _UploadedFile) -> None:
    _clear_error()
    data = uploaded.getvalue()
    st.session_state[_SESSION_BYTES] = data
    try:
        video = client.upload_video(
            BytesIO(data),
            filename=str(uploaded.name),
            content_type="application/octet-stream",
        )
        created = client.create_analysis(video.video_id)
    except DashboardClientError as error:
        _set_error(error.safe.message)
        return
    st.session_state[_SESSION_VIDEO] = str(video.video_id)
    st.session_state[_SESSION_ANALYSIS] = str(created.analysis_id)
    st.session_state[_SESSION_POLL] = 0
    st.session_state[_SESSION_SEEK] = 0
    st.session_state[_SESSION_SHOT] = None


def _cancel(client: AnalyzerClient) -> None:
    analysis_id = st.session_state[_SESSION_ANALYSIS]
    if analysis_id is None:
        return
    try:
        client.cancel(UUID(str(analysis_id)))
    except DashboardClientError as error:
        _set_error(error.safe.message)


def _analysis_body(client: AnalyzerClient, analysis_id: UUID) -> None:
    if st.session_state[_SESSION_ERROR]:
        st.error(failed_job(str(st.session_state[_SESSION_ERROR])))
    try:
        status = client.get_status(analysis_id)
    except DashboardClientError as error:
        st.error(failed_job(error.safe.message))
        return
    st.subheader("Job")
    st.write(f"**{status.state.value}**, progress {status.progress:.0%}")
    st.caption(state_caption(status.state))
    st.caption(progress_caption())
    st.write(
        "Completed stages:",
        ", ".join(status.completed_stages) or "none",
        "Active:",
        ", ".join(status.active_stages) or "none",
        "Unavailable pillars:",
        ", ".join(status.unavailable_stages) or "none",
    )
    if status.error is not None:
        st.error(failed_job(status.error.message))
    if not is_terminal_status(status):
        delay = poll_delay_ms(int(st.session_state[_SESSION_POLL]))
        st.session_state[_SESSION_POLL] = int(st.session_state[_SESSION_POLL]) + 1
        st.info(f"Waiting {delay} ms before the next status read.")
        time.sleep(delay / 1000)
        st.rerun()
    if status.state in {AnalysisState.CANCELED, AnalysisState.FAILED}:
        return
    try:
        report = client.get_report(analysis_id)
    except DashboardClientError as error:
        st.warning(error.safe.message)
        return
    tabs = st.tabs(["Overview", "Shot inspector", "Tension proxy"])
    with tabs[0]:
        _overview(client, analysis_id, report)
    with tabs[1]:
        _shot_inspector(client, analysis_id, report)
    with tabs[2]:
        _tension(client, analysis_id, report)


def _overview(client: AnalyzerClient, analysis_id: UUID, report: AnalysisReport) -> None:
    video = report.video
    st.markdown("#### Source (measured)")
    st.write(
        f"{video.width}x{video.height}, {format_timecode(video.duration_ms)}, "
        f"codec `{video.video_codec}`, audio {'yes' if video.has_audio else 'no'}"
    )
    st.caption(f"content sha256 `{video.content_sha256}`, config `{report.configuration_hash}`")
    st.markdown("#### Availability")
    rows = pillar_rows(report.availability)
    st.dataframe(
        {
            "pillar": [row.name for row in rows],
            "availability": [row.availability for row in rows],
            "kind": [row.kind for row in rows],
        },
        hide_index=True,
        use_container_width=True,
    )
    st.caption(no_audio(report.availability.audio))
    st.caption(critic_caption(report.availability.critic))
    st.markdown(f"#### {interpretation_label()}")
    st.caption(evidence_chip_caption())
    chips = evidence_chips(CriticInput.from_report(report))
    st.write(", ".join(f"{chip.label} ({chip.kind})" for chip in chips))
    try:
        critique = client.get_critique(analysis_id)
    except DashboardClientError:
        critique = Critique(status=MetricStatus.NOT_COMPUTED)
    if critique.status is MetricStatus.OK and critique.text is not None:
        st.write(critique.text)
        st.caption(f"Interpreted, optional, {critique.prompt_version}, {critique.model_name}")
    else:
        st.caption(critic_caption(report.availability.critic))
    st.markdown("#### Detected shots")
    bars = shot_bars(report)
    figure = go.Figure()
    for bar in bars:
        figure.add_trace(
            go.Bar(
                x=[bar.duration_ms],
                y=["detected shots"],
                base=[bar.start_ms],
                orientation="h",
                name=bar.label,
                hovertemplate=bar.label + "<extra></extra>",
            )
        )
    figure.update_layout(
        barmode="overlay",
        height=160,
        showlegend=False,
        xaxis_title="time (ms)",
        margin={"l": 120, "r": 20, "t": 20, "b": 40},
        font=_CHART_FONT,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )
    event = st.plotly_chart(
        figure, on_select="rerun", key="shot-overview", use_container_width=True
    )
    _apply_shot_click(event, bars)
    st.caption("Intervals between detected edit boundaries. Not narrative scenes.")
    st.markdown("#### Shot-length distribution (measured)")
    durations = shot_duration_histogram(report)
    hist = go.Figure(go.Histogram(x=list(durations), nbinsx=min(20, max(1, len(durations)))))
    hist.update_layout(
        xaxis_title="shot duration (ms)",
        yaxis_title="count",
        height=240,
        margin={"l": 40, "r": 20, "t": 20, "b": 40},
        font=_CHART_FONT,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )
    st.plotly_chart(hist, use_container_width=True)
    st.write(
        f"Average shot length {report.summary.average_shot_length_ms:.1f} ms, "
        f"median {report.summary.median_shot_length_ms:.1f} ms, "
        f"{report.summary.shots_per_minute:.2f} shots/min"
    )


def _shot_inspector(client: AnalyzerClient, analysis_id: UUID, report: AnalysisReport) -> None:
    options = {f"shot {item.shot.index}": item.shot.shot_id for item in report.shots}
    labels = tuple(options)
    default_index = 0
    stored = st.session_state[_SESSION_SHOT]
    if stored is not None:
        for index, identifier in enumerate(options.values()):
            if str(identifier) == str(stored):
                default_index = index
                break
    selected_label = st.selectbox("Shot", labels, index=default_index)
    shot_id = options[selected_label]
    try:
        shot = client.get_shot(analysis_id, shot_id)
    except DashboardClientError:
        shot = next(item for item in report.shots if item.shot.shot_id == shot_id)
    if st.button("Seek upload to this shot"):
        st.session_state[_SESSION_SHOT] = str(shot.shot.shot_id)
        _maybe_seek(shot.shot.time_range.start_ms)
    st.write(
        f"{format_timecode(shot.shot.time_range.start_ms)} - "
        f"{format_timecode(shot.shot.time_range.end_ms)} "
        f"({format_timecode(shot.shot.time_range.duration_ms)})"
    )
    _chromatic_panel(shot)
    _spatial_panel(shot)
    _provenance_panel(shot)


def _chromatic_panel(shot: ShotAnalysis) -> None:
    st.markdown("#### Palette and lightness")
    st.caption(palette_caption())
    if shot.chromatic.status is MetricStatus.OK and shot.chromatic.value is not None:
        bars = palette_bars(shot.chromatic.value.palette)
        st.markdown(palette_svg(bars), unsafe_allow_html=True)
        for bar in bars:
            st.code(f"{bar.hex_color}  {bar.width_pct:.2f}%", language=None)
        st.caption(lighting_caption())
        st.write(
            f"Lighting-key estimate: `{shot.chromatic.value.lighting_key.value}` "
            f"({kind_for_metric_status(shot.chromatic.status)} colour; "
            f"estimated lighting-key label)"
        )
        markers = lightness_markers(shot)
        if markers is not None:
            st.write(
                f"L* p10 {markers['p10']:.1f}, p50 {markers['p50']:.1f}, "
                f"p90 {markers['p90']:.1f}, shadow {markers['shadow_ratio']:.2f}, "
                f"highlight {markers['highlight_ratio']:.2f}"
            )
    else:
        st.info(shot.chromatic.reason_code or "chromatic unavailable")
    ids = ", ".join(str(item) for item in shot.chromatic.evidence_sample_ids) or "none"
    st.caption(f"Evidence sample ids: {ids}")


def _spatial_panel(shot: ShotAnalysis) -> None:
    st.markdown("#### Composition")
    st.caption(spatial_caption())
    st.markdown(no_subject(shot))
    value = shot.spatial.value if shot.spatial.status is MetricStatus.OK else None
    st.markdown(composition_svg(value), unsafe_allow_html=True)


def _provenance_panel(shot: ShotAnalysis) -> None:
    st.markdown("#### Provenance")
    with st.expander("Method versions and warnings"):
        for name, measurement in (
            ("chromatic", shot.chromatic),
            ("spatial", shot.spatial),
            ("temporal", shot.temporal),
        ):
            method = measurement.method
            st.write(
                f"**{name}**, `{method.method}` `{method.method_version}`, "
                f"status {measurement.status.value}, config `{method.config_hash}`"
            )
            if measurement.reason_code:
                st.write(f"reason: `{measurement.reason_code}`")


def _tension(client: AnalyzerClient, analysis_id: UUID, report: AnalysisReport) -> None:
    st.caption(tension_caption())
    query = timeline_query(report.video.duration_ms)
    try:
        window = client.get_timeline(analysis_id, **query)
    except DashboardClientError as error:
        st.info(error.safe.message)
        return
    series = tension_series(window, report)
    figure = go.Figure()
    traces = (
        ("cut activity", series.cut_activity, "#4C6EF5"),
        ("audio activity", series.audio_activity, "#82C91E"),
        ("motion activity", series.motion_activity, "#FAB005"),
        ("tension proxy", series.combined_proxy, "#212529"),
    )
    for name, values, color in traces:
        figure.add_trace(
            go.Scatter(
                x=list(series.at_ms),
                y=list(values),
                name=name,
                line={"color": color},
                hovertemplate=(
                    f"{name}<br>%{{x}} ms<br>%{{y:.3f}}<br>{series.method_version}<extra></extra>"
                ),
            )
        )
    for boundary in series.shot_boundary_ms:
        figure.add_vline(x=boundary, line_dash="dash", line_color="#868E96")
    figure.update_layout(
        xaxis_title="time (ms)",
        yaxis_title="activity / proxy",
        yaxis={"range": [0, 1]},
        height=360,
        margin={"l": 40, "r": 20, "t": 20, "b": 40},
        font=_CHART_FONT,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
    )
    event = st.plotly_chart(
        figure, on_select="rerun", key="tension-chart", use_container_width=True
    )
    points = _selection_points(event)
    if points:
        first = points[0]
        at_ms = first.get("x") if isinstance(first, dict) else getattr(first, "x", None)
        if isinstance(at_ms, int | float):
            _maybe_seek(int(at_ms))
    st.caption(series.warning)
    st.caption(f"Window {query['start_ms']}-{query['end_ms']} ms, max_points {query['max_points']}")


def _apply_shot_click(event: object, bars: tuple[ShotBar, ...]) -> None:
    points = _selection_points(event)
    if not points:
        return
    first = points[0]
    if isinstance(first, dict):
        curve = first.get("curve_number")
    else:
        curve = getattr(first, "curve_number", None)
    if isinstance(curve, int) and 0 <= curve < len(bars):
        bar = bars[curve]
        st.session_state[_SESSION_SHOT] = str(bar.shot_id)
        _maybe_seek(bar.start_ms)


if __name__ == "__main__":
    main()
