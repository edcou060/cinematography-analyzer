"""Integer-millisecond time and rational frame rates.

Media instants and durations that are persisted, transported, hashed, or compared
are integers with an ``_ms`` suffix. Conversion from stream time bases happens at
ingestion; conversion to seconds happens at presentation. Neither happens here.
"""

from typing import Annotated, Self

from pydantic import Field, model_validator

from cine_analyzer.domain.types import StrictModel

__all__ = ["Rational", "TimeRangeMs"]


class TimeRangeMs(StrictModel):
    """Half-open interval ``[start_ms, end_ms)`` on the media timeline."""

    start_ms: Annotated[
        int,
        Field(
            ge=0,
            description="Inclusive start on the media timeline, integer milliseconds.",
        ),
    ]
    end_ms: Annotated[
        int,
        Field(
            gt=0,
            description="Exclusive end on the media timeline, integer milliseconds.",
        ),
    ]

    @model_validator(mode="after")
    def end_follows_start(self) -> Self:
        if self.end_ms <= self.start_ms:
            message = "end_ms must be greater than start_ms"
            raise ValueError(message)
        return self

    @property
    def duration_ms(self) -> int:
        """Length of the interval, integer milliseconds."""
        return self.end_ms - self.start_ms


class Rational(StrictModel):
    """Exact frame-rate fraction. A float is display-only and is not stored here."""

    numerator: int
    denominator: Annotated[int, Field(gt=0, description="Non-zero denominator.")]
