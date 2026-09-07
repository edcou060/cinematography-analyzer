"""Public JSON Schema snapshots for durable envelopes."""

import json
from pathlib import Path
from typing import Any

from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisStatusResponse, StageCommand, StageResult
from cine_analyzer.domain.media import SamplingManifest, SamplingPlan, VideoMetadata
from cine_analyzer.domain.report import AnalysisReport
from cine_analyzer.domain.shots import ShotSet
from cine_analyzer.domain.timeline import Timeline

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

PUBLIC_MODELS: dict[str, type[Any]] = {
    "analysis_config": AnalysisConfig,
    "analysis_report": AnalysisReport,
    "analysis_status_response": AnalysisStatusResponse,
    "sampling_plan": SamplingPlan,
    "sampling_manifest": SamplingManifest,
    "shot_set": ShotSet,
    "stage_command": StageCommand,
    "stage_result": StageResult,
    "timeline": Timeline,
    "video_metadata": VideoMetadata,
}


def _schema(model: type[Any]) -> dict[str, Any]:
    return model.model_json_schema()


def test_json_schema_snapshots_match() -> None:
    missing: list[str] = []
    drifted: list[str] = []
    for name, model in PUBLIC_MODELS.items():
        path = SNAPSHOT_DIR / f"{name}.schema.json"
        rendered = json.dumps(_schema(model), indent=2, sort_keys=True) + "\n"
        if not path.is_file():
            missing.append(f"{path.name}\n{rendered}")
            continue
        if path.read_text(encoding="utf-8") != rendered:
            drifted.append(name)
    assert missing == [], "Missing schema snapshots:\n" + "\n".join(missing)
    assert drifted == [], (
        f"Schema snapshots drifted: {drifted}. "
        "Review field descriptions and units, then regenerate."
    )


def test_schema_snapshots_name_millisecond_units() -> None:
    report = json.dumps(AnalysisReport.model_json_schema())
    assert "integer milliseconds" in report
    config = json.dumps(AnalysisConfig.model_json_schema())
    assert "integer milliseconds" in config
