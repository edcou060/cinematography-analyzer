"""Shared constrained types for every domain contract.

Boundary models reject unknown fields, freeze after validation, and strip incidental
whitespace. Time, ratios, and colour encodings are named here so a later module cannot
quietly invent a second representation.
"""

from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "HEX_COLOR_PATTERN",
    "SCHEMA_VERSION",
    "SHA256_PATTERN",
    "HexColor",
    "MetricStatus",
    "NonNegativeFloat",
    "Score",
    "Sha256Hex",
    "StrictModel",
]

SCHEMA_VERSION: Final = "1.0"
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
HEX_COLOR_PATTERN: Final = r"^#[0-9A-F]{6}$"

Score = Annotated[
    float,
    Field(
        ge=0.0,
        le=1.0,
        description="Ratio in [0, 1]. Percentages are a presentation concern.",
    ),
]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
HexColor = Annotated[
    str,
    Field(
        pattern=HEX_COLOR_PATTERN,
        description="sRGB hex colour, uppercase, with a leading #.",
    ),
]
Sha256Hex = Annotated[
    str,
    Field(pattern=SHA256_PATTERN, description="Lowercase hex SHA-256 digest."),
]


class StrictModel(BaseModel):
    """Frozen envelope that refuses structural drift."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class MetricStatus(StrEnum):
    """Why a measurement envelope does or does not carry a value.

    ``OK`` is the only status that may hold a value. Every other status is a
    machine-readable absence, never an unexplained null.
    """

    OK = "OK"
    NOT_COMPUTED = "NOT_COMPUTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_SUBJECT = "NO_SUBJECT"
    NO_AUDIO = "NO_AUDIO"
    FAILED = "FAILED"
