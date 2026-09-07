"""Timeline ordering and schema version."""

import pytest
from pydantic import ValidationError
from tests.factories import ANALYSIS_ID

from cine_analyzer.domain.temporal import AudioWindowValue, TensionComponents
from cine_analyzer.domain.timeline import Timeline, TimelinePoint
from cine_analyzer.domain.types import SCHEMA_VERSION


def _point(at_ms: int, shot_index: int = 0) -> TimelinePoint:
    return TimelinePoint(
        at_ms=at_ms,
        shot_index=shot_index,
        tension=TensionComponents(
            cut_activity=0.1,
            audio_activity=0.2,
            motion_activity=0.3,
            combined_proxy=0.2,
        ),
        audio=AudioWindowValue(rms_dbfs=-20.0, onset_strength=0.1, spectral_flux=0.2),
    )


def test_points_must_increase_in_time() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        Timeline(
            schema_version=SCHEMA_VERSION,
            analysis_id=ANALYSIS_ID,
            points=(_point(1000), _point(1000)),
        )


def test_an_unsupported_timeline_schema_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        Timeline(schema_version="2.0", analysis_id=ANALYSIS_ID, points=())


def test_a_valid_timeline_is_accepted() -> None:
    timeline = Timeline(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        points=(_point(0), _point(1000), _point(2000)),
    )

    assert [point.at_ms for point in timeline.points] == [0, 1000, 2000]
