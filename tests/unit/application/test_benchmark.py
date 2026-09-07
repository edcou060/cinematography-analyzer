"""Benchmark manifest load, skip, and validation."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cine_analyzer.application.benchmark import (
    BenchmarkClipResult,
    BenchmarkManifest,
    BenchmarkReport,
    BenchmarkRun,
    _commit,
    _top_functions,
    load_manifest,
    run_benchmark,
    validate_benchmark_report,
)
from cine_analyzer.domain.config import AnalysisConfig, canonical_hash


def _run(**overrides: object) -> BenchmarkRun:
    payload: dict[str, object] = {
        "wall_ms": 10,
        "rss_raw": 1,
        "rtf_milli": 1,
        "jpeg_reads": 1,
        "jpeg_hits": 0,
        "config_hash": canonical_hash(AnalysisConfig()),
        "pipeline_version": "0.1.0",
        "golden_status": "pass",
        "duration_ms": 1000,
    }
    payload.update(overrides)
    return BenchmarkRun.model_validate(payload)


def test_load_manifest_and_validate_success(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "profile": "cpu_core",
                "clips": [{"id": "missing", "path": "nope.mp4", "required": True}],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_manifest(manifest_path)
    assert loaded.clips[0].id == "missing"
    hashed = canonical_hash(AnalysisConfig())
    report = BenchmarkReport(
        schema_version="1.0",
        profile="cpu_core",
        commit="dev",
        hardware="test",
        pipeline_version="0.1.0",
        configuration_hash=hashed,
        jpeg_cache="on",
        clips=(
            BenchmarkClipResult(
                clip_id="a",
                relative_path="fixtures/video/a.mp4",
                cold=_run(),
                warm=_run(),
            ),
        ),
    )
    ok, reason = validate_benchmark_report(report, expected_hash=hashed)
    assert ok is True
    assert reason == "ok"


def test_validate_rejects_hash_skip_and_bad_golden() -> None:
    hashed = canonical_hash(AnalysisConfig())
    empty = BenchmarkReport(
        schema_version="1.0",
        profile="cpu_core",
        commit="dev",
        hardware="test",
        pipeline_version="0.1.0",
        configuration_hash=hashed,
        jpeg_cache="on",
        clips=(
            BenchmarkClipResult(
                clip_id="a",
                relative_path="x",
                skipped_reason="missing",
            ),
        ),
    )
    ok, reason = validate_benchmark_report(empty, expected_hash=hashed)
    assert ok is False
    assert "fixture" in reason
    wrong_hash, _ = validate_benchmark_report(empty, expected_hash="0" * 64)
    assert wrong_hash is False
    failed = BenchmarkReport(
        schema_version="1.0",
        profile="cpu_core",
        commit="dev",
        hardware="test",
        pipeline_version="0.1.0",
        configuration_hash=hashed,
        jpeg_cache="on",
        clips=(
            BenchmarkClipResult(
                clip_id="a",
                relative_path="x",
                cold=_run(golden_status="fail"),
            ),
        ),
    )
    bad, _reason = validate_benchmark_report(failed, expected_hash=hashed)
    assert bad is False
    cold_only = BenchmarkReport(
        schema_version="1.0",
        profile="cpu_core",
        commit="dev",
        hardware="test",
        pipeline_version="0.1.0",
        configuration_hash=hashed,
        jpeg_cache="on",
        clips=(
            BenchmarkClipResult(
                clip_id="a",
                relative_path="x",
                cold=_run(),
            ),
        ),
    )
    ok_cold, reason_cold = validate_benchmark_report(cold_only, expected_hash=hashed)
    assert ok_cold is True
    assert reason_cold == "ok"
    negative = BenchmarkReport(
        schema_version="1.0",
        profile="cpu_core",
        commit="dev",
        hardware="test",
        pipeline_version="0.1.0",
        configuration_hash=hashed,
        jpeg_cache="on",
        clips=(
            BenchmarkClipResult(
                clip_id="a",
                relative_path="x",
                cold=_run(rtf_milli=-1),
            ),
        ),
    )
    neg, _ = validate_benchmark_report(negative, expected_hash=hashed)
    assert neg is False


def test_run_benchmark_skips_missing_clips(tmp_path: Path) -> None:
    manifest = BenchmarkManifest(
        schema_version="1.0",
        profile="cpu_core",
        clips=(
            {"id": "gone", "path": "missing.mp4", "required": True},  # type: ignore[arg-type]
        ),
    )
    parsed = BenchmarkManifest.model_validate(
        {
            "schema_version": "1.0",
            "profile": "cpu_core",
            "clips": [{"id": "gone", "path": "missing.mp4", "required": True}],
        }
    )
    del manifest
    report = run_benchmark(parsed, repo_root=tmp_path, work_root=tmp_path / "work", profile=True)
    assert report.clips[0].skipped_reason is not None
    assert report.jpeg_cache == "on"


def test_commit_and_profile_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cine_analyzer.application.benchmark.subprocess.run",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("git")),
    )
    assert _commit(tmp_path) == "unknown"
    monkeypatch.setattr(
        "cine_analyzer.application.benchmark.subprocess.run",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["git"], timeout=1)),
    )
    assert _commit(tmp_path) == "unknown"

    class _Done:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(
        "cine_analyzer.application.benchmark.subprocess.run",
        lambda *_a, **_k: _Done(),
    )
    assert _commit(tmp_path) == "uncommitted"

    class _Ok:
        returncode = 0
        stdout = "abc\n"

    monkeypatch.setattr(
        "cine_analyzer.application.benchmark.subprocess.run",
        lambda *_a, **_k: _Ok(),
    )
    assert _commit(tmp_path) == "abc"

    class _Blank:
        returncode = 0
        stdout = "\n"

    monkeypatch.setattr(
        "cine_analyzer.application.benchmark.subprocess.run",
        lambda *_a, **_k: _Blank(),
    )
    assert _commit(tmp_path) == "unknown"

    class _Stat:
        totaltime = 1.0
        code = SimpleNamespace(co_name="load_decoded_jpegs")

    assert _top_functions(SimpleNamespace(getstats=lambda: [_Stat()])) == ("load_decoded_jpegs",)
    assert _top_functions(SimpleNamespace(getstats=list)) == ()


def test_run_benchmark_times_a_generated_clip(video_fixtures: Path, tmp_path: Path) -> None:
    parsed = BenchmarkManifest.model_validate(
        {
            "schema_version": "1.0",
            "profile": "cpu_core",
            "clips": [
                {
                    "id": "two_color_cut",
                    "path": "fixtures/video/two_color_cut.mp4",
                    "required": True,
                }
            ],
        }
    )
    repo_root = video_fixtures.parent.parent
    report = run_benchmark(parsed, repo_root=repo_root, work_root=tmp_path / "work")
    assert report.clips[0].cold is not None
    assert report.clips[0].warm is not None
    assert report.clips[0].cold.jpeg_reads >= 1
    ok, _reason = validate_benchmark_report(report, expected_hash=canonical_hash(AnalysisConfig()))
    assert ok is True
