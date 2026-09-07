"""Compact critic input. Presentation boundary: seconds, not frames or names."""

from statistics import median
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from cine_analyzer.domain.chromatics import LightingKeyLabel
from cine_analyzer.domain.report import AnalysisReport, StageAvailability
from cine_analyzer.domain.types import SCHEMA_VERSION, HexColor, Score, StrictModel

__all__ = [
    "CRITIC_PROMPT_VERSION",
    "CompositionFacts",
    "CriticInput",
    "CriticOutput",
    "EditingFacts",
    "LightingFacts",
    "TensionFacts",
]

CRITIC_PROMPT_VERSION = "critic-prompt-v1"
_MAX_SENTENCE_CHARS = 200
_MAX_PALETTE = 3
_MAX_PEAKS = 8


class EditingFacts(StrictModel):
    """Detected-shot counts and durations in display seconds."""

    shot_count: Annotated[int, Field(ge=1)]
    asl_seconds: Annotated[float, Field(gt=0.0)]
    median_seconds: Annotated[float, Field(gt=0.0)]


class LightingFacts(StrictModel):
    """Lighting-key estimate coverage. Labels are estimates, not intent."""

    low_key_ratio: Score
    valid_shot_ratio: Score


class CompositionFacts(StrictModel):
    """Subject-geometry coverage. Thirds proximity is not composition quality."""

    valid_shot_ratio: Score
    median_thirds_proximity: Score | None = None


class TensionFacts(StrictModel):
    """Tension-proxy peaks in display seconds. Not audience emotion."""

    peak_seconds: Annotated[tuple[float, ...], Field(max_length=_MAX_PEAKS)] = ()
    audio_available: bool


class CriticInput(StrictModel):
    """Metrics-only envelope. Filenames, paths, frames, and ids are excluded."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    editing: EditingFacts
    lighting: LightingFacts
    palette: Annotated[tuple[HexColor, ...], Field(max_length=_MAX_PALETTE)] = ()
    composition: CompositionFacts
    tension_proxy: TensionFacts

    @classmethod
    def from_report(cls, report: AnalysisReport, *, peak_ms: tuple[int, ...] = ()) -> Self:
        """Project a report into CriticInput. Drops names, paths, and frames."""
        shot_count = report.summary.shot_count
        low_key = 0
        chromatic_n = 0
        spatial_n = 0
        weights: dict[str, float] = {}
        thirds: list[float] = []
        for item in report.shots:
            chromatic = item.chromatic.value
            if chromatic is not None:
                chromatic_n += 1
                if chromatic.lighting_key is LightingKeyLabel.LOW_KEY_ESTIMATE:
                    low_key += 1
                duration = float(item.shot.time_range.duration_ms)
                for swatch in chromatic.palette:
                    weights[swatch.rgb.hex] = (
                        weights.get(swatch.rgb.hex, 0.0) + swatch.proportion * duration
                    )
            spatial = item.spatial.value
            if spatial is not None:
                spatial_n += 1
                thirds.append(spatial.thirds_proximity_score)
        palette = tuple(
            sorted(weights, key=lambda hex_color: (-weights[hex_color], hex_color))[:_MAX_PALETTE]
        )
        return cls(
            editing=EditingFacts(
                shot_count=shot_count,
                asl_seconds=_seconds(report.summary.average_shot_length_ms),
                median_seconds=_seconds(report.summary.median_shot_length_ms),
            ),
            lighting=LightingFacts(
                low_key_ratio=_ratio(low_key, chromatic_n),
                valid_shot_ratio=_ratio(chromatic_n, shot_count),
            ),
            palette=palette,
            composition=CompositionFacts(
                valid_shot_ratio=_ratio(spatial_n, shot_count),
                median_thirds_proximity=None if not thirds else round(float(median(thirds)), 2),
            ),
            tension_proxy=TensionFacts(
                peak_seconds=tuple(_peak_seconds(ms) for ms in peak_ms[:_MAX_PEAKS]),
                audio_available=(
                    report.video.has_audio
                    and report.availability.audio is StageAvailability.COMPLETE
                ),
            ),
        )


class CriticOutput(StrictModel):
    """At most three short sentences. Validated before storage."""

    sentences: Annotated[tuple[str, ...], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def sentences_are_nonempty_and_short(self) -> Self:
        for sentence in self.sentences:
            if sentence == "":
                message = "a critic sentence cannot be empty"
                raise ValueError(message)
            if len(sentence) > _MAX_SENTENCE_CHARS:
                message = "a critic sentence exceeds the length limit"
                raise ValueError(message)
        return self

    def as_text(self) -> str:
        """Join sentences for the stored Critique.text field."""
        return " ".join(self.sentences)


def _seconds(ms: float) -> float:
    return round(float(ms) / 1000.0, 2)


def _peak_seconds(ms: int) -> float:
    return round(float(ms) / 1000.0, 1)


def _ratio(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(part / whole, 2)
