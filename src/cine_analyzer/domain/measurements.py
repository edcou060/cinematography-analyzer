"""Measurement envelope: a value, or a named reason it is absent.

``null`` alone cannot distinguish no audio, no person, not requested, failed, or
an old schema. The envelope is what lets an aggregator degrade truthfully.
"""

from typing import Self
from uuid import UUID

from pydantic import model_validator

from cine_analyzer.domain.artifacts import MethodProvenance
from cine_analyzer.domain.types import MetricStatus, Score, StrictModel

__all__ = ["Measurement"]


class Measurement[T](StrictModel):
    """Typed value plus the status that licenses it."""

    status: MetricStatus
    value: T | None
    confidence: Score | None = None
    reason_code: str | None = None
    evidence_sample_ids: tuple[UUID, ...] = ()
    method: MethodProvenance

    @model_validator(mode="after")
    def status_matches_value(self) -> Self:
        if self.status is MetricStatus.OK:
            if self.value is None:
                message = "OK measurement requires a value"
                raise ValueError(message)
            if self.reason_code is not None:
                message = "OK measurement must not carry a reason_code"
                raise ValueError(message)
            return self
        if self.value is not None:
            message = "non-OK measurement must not contain a value"
            raise ValueError(message)
        if self.reason_code is None or self.reason_code == "":
            message = "non-OK measurement requires a reason_code"
            raise ValueError(message)
        return self
