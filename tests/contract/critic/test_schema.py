"""CriticInput public envelope matches the phase compact example."""

from cine_analyzer.domain.critic import CriticInput

EXAMPLE = {
    "schema_version": "1.0",
    "editing": {"shot_count": 18, "asl_seconds": 3.42, "median_seconds": 2.80},
    "lighting": {"low_key_ratio": 0.62, "valid_shot_ratio": 0.94},
    "palette": ["#17212B", "#A66B42", "#D5C2A8"],
    "composition": {"valid_shot_ratio": 0.71, "median_thirds_proximity": 0.78},
    "tension_proxy": {"peak_seconds": [12.0, 37.5], "audio_available": True},
}


def test_phase_example_validates() -> None:
    payload = CriticInput.model_validate(EXAMPLE)
    dumped = payload.model_dump(mode="json")
    assert dumped["editing"]["shot_count"] == 18
    assert "original_filename" not in dumped
    assert "frames" not in dumped
    assert payload.palette[0] == "#17212B"
