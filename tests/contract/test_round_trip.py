"""Serialize → deserialize round trips preserve equality for public envelopes."""

from tests.factories import (
    ANALYSIS_ID,
    make_artifact,
    make_provenance,
    make_report,
    make_sampling_plan,
    make_shot_set,
    make_stage_command,
    make_stage_result,
    make_video,
)

from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState, AnalysisStatusResponse
from cine_analyzer.domain.shots import ShotBoundary, TransitionKind
from cine_analyzer.domain.temporal import TensionComponents
from cine_analyzer.domain.timeline import Timeline, TimelinePoint
from cine_analyzer.domain.types import SCHEMA_VERSION


def _round_trip(model: object) -> None:
    cls = type(model)
    restored = cls.model_validate_json(model.model_dump_json())  # type: ignore[attr-defined]
    assert restored == model


def test_public_envelopes_round_trip() -> None:
    _round_trip(AnalysisConfig())
    _round_trip(make_video())
    _round_trip(make_shot_set())
    _round_trip(make_sampling_plan())
    _round_trip(make_stage_command())
    _round_trip(make_stage_result())
    _round_trip(make_report())
    _round_trip(
        AnalysisStatusResponse(
            analysis_id=ANALYSIS_ID,
            state=AnalysisState.QUEUED,
            progress=0.0,
            completed_stages=(),
            active_stages=(),
            unavailable_stages=("spatial",),
        )
    )
    _round_trip(
        ShotBoundary(
            boundary_id=ANALYSIS_ID,
            position_ms=1500,
            transition=TransitionKind.CUT,
            detector_score=0.9,
        )
    )
    _round_trip(
        Timeline(
            schema_version=SCHEMA_VERSION,
            analysis_id=ANALYSIS_ID,
            points=(
                TimelinePoint(
                    at_ms=0,
                    shot_index=0,
                    tension=TensionComponents(
                        cut_activity=0.1,
                        audio_activity=0.0,
                        motion_activity=0.0,
                        combined_proxy=0.1,
                    ),
                ),
            ),
        )
    )
    _round_trip(make_artifact())
    _round_trip(make_provenance())
