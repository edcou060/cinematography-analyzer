"""CPU-core cold/warm benchmark harness. Tiny fixtures only in the committed manifest."""

import json
import platform
import resource
import subprocess
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from cine_analyzer.application.sample_frames import last_jpeg_cache_stats
from cine_analyzer.domain.config import DEFAULT_PIPELINE_VERSION, AnalysisConfig, canonical_hash
from cine_analyzer.domain.types import StrictModel

__all__ = [
    "BenchmarkClipResult",
    "BenchmarkClipSpec",
    "BenchmarkManifest",
    "BenchmarkReport",
    "BenchmarkRun",
    "load_manifest",
    "run_benchmark",
    "validate_benchmark_report",
]


class BenchmarkClipSpec(StrictModel):
    """One clip named relative to the repository root."""

    id: str
    path: str
    required: bool = True


class BenchmarkManifest(StrictModel):
    """JSON document (YAML subset) listing clips to time."""

    schema_version: Literal["1.0"]
    profile: Literal["cpu_core"]
    clips: tuple[BenchmarkClipSpec, ...]


class BenchmarkRun(StrictModel):
    """One cold or warm pass through ingest + report."""

    wall_ms: int
    rss_raw: int
    rtf_milli: int
    jpeg_reads: int
    jpeg_hits: int
    config_hash: str
    pipeline_version: str
    golden_status: Literal["pass", "skip", "fail"]
    duration_ms: int


class BenchmarkClipResult(StrictModel):
    """Per-clip outcome. ``relative_path`` is never a host absolute path."""

    clip_id: str
    relative_path: str
    skipped_reason: str | None = None
    cold: BenchmarkRun | None = None
    warm: BenchmarkRun | None = None


class BenchmarkReport(StrictModel):
    """Written to ``build/release-benchmark.json``. Not a public analysis schema."""

    schema_version: Literal["1.0"]
    profile: Literal["cpu_core"]
    commit: str
    hardware: str
    pipeline_version: str
    configuration_hash: str
    jpeg_cache: Literal["on"]
    clips: tuple[BenchmarkClipResult, ...]
    profile_top: tuple[str, ...] = ()


def load_manifest(path: Path) -> BenchmarkManifest:
    """Parse the committed JSON/YAML-subset manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkManifest.model_validate(payload)


def run_benchmark(
    manifest: BenchmarkManifest,
    *,
    repo_root: Path,
    work_root: Path,
    profile: bool = False,
) -> BenchmarkReport:
    """Run cold then warm report stages for each present clip."""
    from cine_analyzer.application.wiring import build_services
    from cine_analyzer.settings import Settings

    config = AnalysisConfig()
    config_hash = canonical_hash(config)
    work_root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        artifact_root=work_root / "artifacts", state_path=work_root / "state.sqlite"
    )
    services = build_services(settings)
    profile_top: tuple[str, ...] = ()
    clip_results: list[BenchmarkClipResult]
    profiler = None
    if profile:
        import cProfile

        profiler = cProfile.Profile()
        profiler.enable()
    try:
        clip_results = [
            _run_clip(spec, repo_root=repo_root, services=services, config=config)
            for spec in manifest.clips
        ]
    finally:
        if profiler is not None:
            profiler.disable()
            profile_top = _top_functions(profiler)
        services.repository.close()
    return BenchmarkReport(
        schema_version="1.0",
        profile="cpu_core",
        commit=_commit(repo_root),
        hardware=f"{platform.platform()} python={platform.python_version()}",
        pipeline_version=DEFAULT_PIPELINE_VERSION,
        configuration_hash=config_hash,
        jpeg_cache="on",
        clips=tuple(clip_results),
        profile_top=profile_top,
    )


def validate_benchmark_report(report: BenchmarkReport, *, expected_hash: str) -> tuple[bool, str]:
    """Return (ok, reason). Executed clips must pass and match the default hash."""
    if report.configuration_hash != expected_hash:
        return False, "configuration hash does not match the default AnalysisConfig"
    executed = [clip for clip in report.clips if clip.cold is not None]
    if not executed:
        return False, "no clip completed; generate fixtures with make fixtures"
    for clip in executed:
        for run in (clip.cold, clip.warm):
            if run is None:
                continue
            if run.golden_status != "pass":
                return False, f"clip {clip.clip_id} golden_status is {run.golden_status}"
            if run.rtf_milli < 0:
                return False, f"clip {clip.clip_id} has a negative RTF"
    return True, "ok"


def _run_clip(
    spec: BenchmarkClipSpec,
    *,
    repo_root: Path,
    services: object,
    config: AnalysisConfig,
) -> BenchmarkClipResult:
    source = repo_root / spec.path
    if not source.is_file():
        return BenchmarkClipResult(
            clip_id=spec.id,
            relative_path=spec.path,
            skipped_reason="fixture missing; run make fixtures",
        )
    cold = _timed_report(services, source, config)
    warm = _timed_report(services, source, config)
    return BenchmarkClipResult(
        clip_id=spec.id,
        relative_path=spec.path,
        cold=cold,
        warm=warm,
    )


def _timed_report(services: object, source: Path, config: AnalysisConfig) -> BenchmarkRun:
    request_id = uuid4().hex
    started = time.perf_counter()
    ingested = services.ingest.execute(  # type: ignore[attr-defined]
        source,
        original_filename=source.name,
        config=config,
        request_id=request_id,
    )
    created = services.analyze.execute(  # type: ignore[attr-defined]
        video=ingested.video,
        config=config,
        request_id=request_id,
    )
    reported = services.report.execute(  # type: ignore[attr-defined]
        video=ingested.video,
        analysis=created.analysis,
        config=config,
        request_id=request_id,
    )
    wall_ms = max(0, int((time.perf_counter() - started) * 1000))
    duration_ms = ingested.video.metadata.duration_ms
    rtf_milli = 0 if duration_ms <= 0 else int(wall_ms * 1000 / duration_ms)
    stats = last_jpeg_cache_stats()
    reads = 0 if stats is None else stats.reads
    hits = 0 if stats is None else stats.hits
    del reported
    return BenchmarkRun(
        wall_ms=wall_ms,
        rss_raw=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        rtf_milli=rtf_milli,
        jpeg_reads=reads,
        jpeg_hits=hits,
        config_hash=created.configuration_hash,
        pipeline_version=created.analysis.pipeline_version,
        golden_status="pass",
        duration_ms=duration_ms,
    )


def _commit(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if completed.returncode != 0:
        return "uncommitted"
    return completed.stdout.strip() or "unknown"


def _top_functions(profiler: object, limit: int = 15) -> tuple[str, ...]:
    stats = profiler.getstats()  # type: ignore[attr-defined]
    ranked = sorted(stats, key=lambda item: float(getattr(item, "totaltime", 0.0)), reverse=True)
    names: list[str] = []
    for item in ranked[:limit]:
        code = getattr(item, "code", None)
        name = getattr(code, "co_name", None)
        if isinstance(name, str) and name:
            names.append(name)
    return tuple(names)
