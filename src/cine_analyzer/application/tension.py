"""Combine named tension-proxy components. Never emotion, never a lone combined curve."""

from cine_analyzer.application.normalize import clip01
from cine_analyzer.domain.config import TensionWeights
from cine_analyzer.domain.temporal import TensionComponents

__all__ = [
    "AUDIO_UNAVAILABLE_WARNING",
    "MOTION_UNAVAILABLE_WARNING",
    "NO_AUDIO_STREAM",
    "combine_tension",
    "effective_weights",
]

NO_AUDIO_STREAM = "no_audio_stream"
AUDIO_UNAVAILABLE_WARNING = "audio_unavailable_weights_renormalized"
MOTION_UNAVAILABLE_WARNING = "motion_unavailable_weights_renormalized"


def effective_weights(
    configured: TensionWeights,
    *,
    audio_available: bool,
    motion_available: bool,
) -> tuple[TensionWeights, tuple[str, ...]]:
    """Zero unavailable components and renormalize remaining weights to one."""
    cut = configured.cut_activity
    audio = configured.audio_activity if audio_available else 0.0
    motion = configured.motion if motion_available else 0.0
    warnings: list[str] = []
    if not audio_available:
        warnings.append(AUDIO_UNAVAILABLE_WARNING)
    if not motion_available:
        warnings.append(MOTION_UNAVAILABLE_WARNING)
    total = cut + audio + motion
    if total <= 0.0:
        return TensionWeights(cut_activity=1.0, audio_activity=0.0, motion=0.0), tuple(warnings)
    return (
        TensionWeights(
            cut_activity=cut / total,
            audio_activity=audio / total,
            motion=motion / total,
        ),
        tuple(warnings),
    )


def combine_tension(
    *,
    cut_activity: float,
    audio_activity: float,
    motion_activity: float,
    weights: TensionWeights,
) -> TensionComponents:
    """Weighted sum clipped to ``[0, 1]``. All three inputs are stored beside the proxy."""
    combined = (
        weights.cut_activity * cut_activity
        + weights.audio_activity * audio_activity
        + weights.motion * motion_activity
    )
    return TensionComponents(
        cut_activity=clip01(cut_activity),
        audio_activity=clip01(audio_activity),
        motion_activity=clip01(motion_activity),
        combined_proxy=clip01(combined),
    )
