"""Canonical hash snapshots. A serialization change that breaks these needs an ADR."""

import json
from pathlib import Path

from cine_analyzer.domain.config import AnalysisConfig

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "config_hashes.json"


def test_default_and_variant_hashes_match_the_snapshot() -> None:
    default = AnalysisConfig()
    critic_on = AnalysisConfig.model_validate(
        {**default.model_dump(mode="json"), "critic": {"enabled": True}}
    )
    longer_shots = AnalysisConfig.model_validate(
        {
            **default.model_dump(mode="json"),
            "shots": {**default.shots.model_dump(mode="json"), "min_shot_ms": 400},
        }
    )
    observed = {
        "default": default.hash(),
        "critic_enabled": critic_on.hash(),
        "min_shot_ms_400": longer_shots.hash(),
    }
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert observed == expected
    assert len({observed["default"], observed["critic_enabled"], observed["min_shot_ms_400"]}) == 3
