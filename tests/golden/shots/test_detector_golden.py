"""Golden shot-boundary evaluation within a documented millisecond tolerance."""

from __future__ import annotations

import json
from pathlib import Path

from cine_analyzer.adapters.media.ffprobe import FfprobeMediaProbe
from cine_analyzer.adapters.vision.pyscenedetect import PySceneDetectShotDetector
from cine_analyzer.domain.config import AnalysisConfig

EXPECTED = Path(__file__).resolve().parent / "expected.json"
TOLERANCE_MS = 200


def _precision_recall(
    predicted: list[int], expected: list[int], *, tolerance_ms: int
) -> tuple[float, float]:
    used: set[int] = set()
    true_positive = 0
    for target in expected:
        best_index: int | None = None
        best_distance = tolerance_ms + 1
        for index, candidate in enumerate(predicted):
            if index in used:
                continue
            distance = abs(candidate - target)
            if distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index is not None and best_distance <= tolerance_ms:
            used.add(best_index)
            true_positive += 1
    false_positive = len(predicted) - true_positive
    false_negative = len(expected) - true_positive
    precision = 1.0 if not predicted else true_positive / (true_positive + false_positive)
    recall = 1.0 if not expected else true_positive / (true_positive + false_negative)
    return precision, recall


def test_golden_clips_match_recorded_detector_behaviour(video_fixtures: Path) -> None:
    payload = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert payload["tolerance_ms"] == TOLERANCE_MS
    detector = PySceneDetectShotDetector()
    probe = FfprobeMediaProbe("ffprobe", timeout_ms=15_000)
    config = AnalysisConfig().shots
    recorded: dict[str, list[int]] = {}
    for name, spec in payload["clips"].items():
        path = video_fixtures / name
        facts = probe.probe(path)
        detected = detector.detect(path, config, duration_ms=facts.duration_ms)
        predicted = [item.position_ms for item in detected.boundaries]
        expected = list(spec["internal_boundaries_ms"])
        precision, recall = _precision_recall(predicted, expected, tolerance_ms=TOLERANCE_MS)
        recorded[name] = predicted
        if spec.get("strict_timing") is True:
            assert precision == 1.0
            assert recall == 1.0
        else:
            assert predicted == expected, (
                f"{name}: recorded golden boundaries drifted. "
                f"predicted={predicted} expected={expected} "
                f"precision={precision:.3f} recall={recall:.3f}"
            )
    assert "two_color_cut.mp4" in recorded
    assert "no_cut.mp4" in recorded
