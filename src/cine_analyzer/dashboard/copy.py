"""User-visible strings. Vocabulary matches the product contract."""

from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.report import ShotAnalysis, StageAvailability
from cine_analyzer.domain.types import MetricStatus

__all__ = [
    "CAVEATS",
    "PAGE_TITLE",
    "SEEK_LIMITATION",
    "SYNC_LIMITATION",
    "caveats_markdown",
    "critic_caption",
    "empty_upload",
    "evidence_chip_caption",
    "failed_job",
    "interpretation_label",
    "lighting_caption",
    "no_audio",
    "no_subject",
    "palette_caption",
    "progress_caption",
    "spatial_caption",
    "state_caption",
    "tension_caption",
]

PAGE_TITLE = "Cinematography analyzer"
SYNC_LIMITATION = (
    "Click a shot or a tension-proxy point to seek the local upload. Streamlit does "
    "not report the playhead back to the app, and seek is truncated to whole seconds."
)
SEEK_LIMITATION = SYNC_LIMITATION
CAVEATS = (
    "Detected shots are algorithmic edit boundaries, not narrative scenes.",
    "Framing labels are heuristic estimates from person geometry, not ground truth.",
    (
        "Thirds proximity is geometric distance to rule-of-thirds intersections, "
        "not a score of good composition."
    ),
    "Lighting-key labels describe sampled pixels, not lighting intent.",
    "Palettes describe the sampled frames, not every frame of the shot.",
    "The tension proxy is a configurable formula. Changing the weights changes the number.",
    (
        "Metrics are comparable only across analyses that share a pipeline version "
        "and configuration hash."
    ),
)


def caveats_markdown() -> str:
    """Sidebar list of honest limitations."""
    return "\n".join(f"- {item}" for item in CAVEATS)


def progress_caption() -> str:
    """Stage-weight progress is not a time remaining animation."""
    return (
        "Progress is the sum of finished stage weights (sampling 0.40, report 0.50, "
        "aggregate 0.10). It is not a wall-clock estimate."
    )


def state_caption(state: AnalysisState) -> str:
    """Short status line for the overview."""
    labels = {
        AnalysisState.QUEUED: "Queued. Waiting for a worker to claim the analysis.",
        AnalysisState.RUNNING: "Running. Stage availability updates as leases complete.",
        AnalysisState.CANCEL_REQUESTED: "Cancel requested. The worker will stop between stages.",
        AnalysisState.CANCELED: "Canceled. No report is produced.",
        AnalysisState.SUCCEEDED: "Succeeded. Every required stage finished.",
        AnalysisState.PARTIAL: (
            "Partial. Required stages finished; at least one optional pillar did not."
        ),
        AnalysisState.FAILED: "Failed. A required stage did not finish.",
    }
    return labels[state]


def empty_upload() -> str:
    """Prompt before a file is chosen."""
    return "Upload one local clip. The dashboard sends it to the API and stores only identifiers."


def no_audio(availability: StageAvailability) -> str:
    """Audio pillar missing is a supported case."""
    if availability is StageAvailability.COMPLETE:
        return "Audio features are present for this clip."
    return (
        "Audio is unavailable. A missing audio stream is a supported case "
        "(reason such as NO_AUDIO / no_audio_stream), not silence."
    )


def no_subject(shot: ShotAnalysis) -> str:
    """Spatial pillar missing or undetermined."""
    spatial = shot.spatial
    if spatial.status is MetricStatus.OK and spatial.value is not None:
        return (
            f"Framing estimate: {spatial.value.framing.value}. "
            "Thirds proximity is geometric, not a composition quality score. "
            f"Confidence {spatial.value.framing_confidence:.2f}; "
            f"track coverage {spatial.value.track_coverage_ratio:.2f}."
        )
    reason = spatial.reason_code or "unavailable"
    return (
        f"No subject geometry for this shot ({reason}). "
        "The base install ships no licensed person detector."
    )


def spatial_caption() -> str:
    """Schematic overlay disclaimer."""
    return (
        "The box is a schematic from shot-median coverage and height, not a detector "
        "overlay on a decoded frame. Guides mark thirds and centre."
    )


def palette_caption() -> str:
    """Palette widths and hex."""
    return "Bar widths follow recorded proportions. Hex values are the stored sRGB encodings."


def lighting_caption() -> str:
    """Lighting-key estimate disclaimer."""
    return (
        "Lighting-key estimate from L* percentiles and shadow/highlight ratios. "
        "It describes sampled pixels, not artistic intent."
    )


def tension_caption() -> str:
    """Tension proxy, never emotion."""
    return (
        "Tension proxy (method tension-v1) with cut, audio, and motion components. "
        "Vertical markers are detected shot boundaries, not narrative scenes. "
        "This is not a measure of audience emotion."
    )


def critic_caption(availability: StageAvailability) -> str:
    """Optional interpretation is separate from metrics."""
    if availability is StageAvailability.NOT_REQUESTED:
        return "Interpretation is disabled. The critic cannot modify measured metrics."
    if availability is StageAvailability.UNAVAILABLE:
        return "Interpretation is unavailable. Measured values are unchanged."
    return "Interpretation is optional prose about an already-validated report."


def interpretation_label() -> str:
    """Dashboard heading. Interpretation is never a measured metric."""
    return "AI interpretation (optional)"


def evidence_chip_caption() -> str:
    """Chips are report fields, not model output."""
    return "Evidence chips are measured or estimated report fields. They are not model output."


def failed_job(message: str) -> str:
    """Safe failure copy. Callers must pass a SafeError message, never a path."""
    return f"The analysis could not be completed. {message}"
