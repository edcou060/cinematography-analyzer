"""Claim audit rejects invented numbers, colours, and forbidden stems."""

from cine_analyzer.application.critic import audit_critique
from cine_analyzer.domain.critic import (
    CompositionFacts,
    CriticInput,
    CriticOutput,
    EditingFacts,
    LightingFacts,
    TensionFacts,
)


def _payload() -> CriticInput:
    return CriticInput(
        editing=EditingFacts(shot_count=18, asl_seconds=3.42, median_seconds=2.8),
        lighting=LightingFacts(low_key_ratio=0.62, valid_shot_ratio=0.94),
        palette=("#17212B", "#A66B42", "#D5C2A8"),
        composition=CompositionFacts(valid_shot_ratio=0.71, median_thirds_proximity=0.78),
        tension_proxy=TensionFacts(peak_seconds=(12.0, 37.5), audio_available=True),
    )


def test_allowed_metrics_pass() -> None:
    output = CriticOutput(
        sentences=(
            "The clip has 18 detected shots with mean length 3.42 s and median 2.8 s.",
            "Duration-weighted palette colours include #17212B, #A66B42, #D5C2A8.",
        )
    )
    ok, reason = audit_critique(output, _payload())
    assert ok is True
    assert reason == "ok"


def test_invented_number_and_hex_are_rejected() -> None:
    payload = _payload()
    bad_number = CriticOutput(sentences=("The clip has 99 detected shots.",))
    ok, reason = audit_critique(bad_number, payload)
    assert ok is False
    assert "number" in reason
    bad_hex = CriticOutput(sentences=("Palette colours include #FFFFFF.",))
    ok_hex, reason_hex = audit_critique(bad_hex, payload)
    assert ok_hex is False
    assert "hex" in reason_hex


def test_forbidden_stems_and_filenames_are_rejected() -> None:
    payload = _payload()
    for sentence in (
        "The director preferred low-key coverage of 0.62.",
        "This is a horror genre clip with 18 shots.",
        "The story peaks at 12.0 s.",
        "File clip.mp4 has 18 shots.",
    ):
        ok, reason = audit_critique(CriticOutput(sentences=(sentence,)), payload)
        assert ok is False, sentence
        assert "forbidden" in reason
