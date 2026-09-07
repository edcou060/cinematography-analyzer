"""Job and stage transition tables, including every illegal pair."""

from collections.abc import Mapping
from enum import StrEnum

import pytest
from pydantic import ValidationError
from tests.factories import make_stage_command, make_stage_result

from cine_analyzer.domain.jobs import (
    ANALYSIS_TRANSITIONS,
    STAGE_TRANSITIONS,
    AnalysisState,
    IllegalStateTransitionError,
    StageState,
    analysis_is_terminal,
    is_partial_outcome,
    stage_is_terminal,
    transition_analysis,
    transition_stage,
)


def _pairs[E: StrEnum](
    enum_cls: type[E],
    table: Mapping[E, frozenset[E]],
) -> list[tuple[E, E, str]]:
    return [
        (current, target, "legal" if target in table[current] else "illegal")
        for current in enum_cls
        for target in enum_cls
    ]


@pytest.mark.parametrize(
    ("current", "target", "legality"),
    _pairs(AnalysisState, ANALYSIS_TRANSITIONS),
)
def test_every_analysis_pair_is_classified(
    current: AnalysisState,
    target: AnalysisState,
    legality: str,
) -> None:
    if legality == "legal":
        assert transition_analysis(current, target) is target
        return
    with pytest.raises(IllegalStateTransitionError, match="illegal analysis"):
        transition_analysis(current, target)


@pytest.mark.parametrize(
    ("current", "target", "legality"),
    _pairs(StageState, STAGE_TRANSITIONS),
)
def test_every_stage_pair_is_classified(
    current: StageState,
    target: StageState,
    legality: str,
) -> None:
    if legality == "legal":
        assert transition_stage(current, target) is target
        return
    with pytest.raises(IllegalStateTransitionError, match="illegal stage"):
        transition_stage(current, target)


@pytest.mark.parametrize(
    "state",
    [AnalysisState.SUCCEEDED, AnalysisState.PARTIAL, AnalysisState.FAILED, AnalysisState.CANCELED],
)
def test_terminal_analysis_states_cannot_regress(state: AnalysisState) -> None:
    assert analysis_is_terminal(state)
    for target in AnalysisState:
        with pytest.raises(IllegalStateTransitionError):
            transition_analysis(state, target)


@pytest.mark.parametrize(
    "state",
    [
        StageState.SUCCEEDED,
        StageState.SKIPPED,
        StageState.FAILED_RETRYABLE,
        StageState.FAILED_TERMINAL,
        StageState.CANCELED,
    ],
)
def test_terminal_stage_attempts_cannot_regress(state: StageState) -> None:
    assert stage_is_terminal(state)


def test_queued_cannot_skip_to_succeeded() -> None:
    with pytest.raises(IllegalStateTransitionError):
        transition_analysis(AnalysisState.QUEUED, AnalysisState.SUCCEEDED)


def test_running_cannot_jump_directly_to_canceled() -> None:
    """Cancellation from a running analysis is cooperative: RUNNING -> CANCEL_REQUESTED."""
    with pytest.raises(IllegalStateTransitionError):
        transition_analysis(AnalysisState.RUNNING, AnalysisState.CANCELED)


def test_partial_requires_required_work_finished_and_an_optional_failure() -> None:
    assert is_partial_outcome(
        required_dependencies_terminal=True,
        optional_stage_failed=True,
    )
    assert not is_partial_outcome(
        required_dependencies_terminal=True,
        optional_stage_failed=False,
    )
    assert not is_partial_outcome(
        required_dependencies_terminal=False,
        optional_stage_failed=True,
    )
    assert not is_partial_outcome(
        required_dependencies_terminal=False,
        optional_stage_failed=False,
    )


def test_an_unsupported_stage_command_schema_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        make_stage_command(schema_version="0.0")


def test_an_unsupported_stage_result_schema_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        make_stage_result(schema_version="0.0")


def test_stage_attempt_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError):
        make_stage_result(attempt=0)
