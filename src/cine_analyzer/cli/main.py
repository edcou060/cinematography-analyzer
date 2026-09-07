"""``cine-analyzer`` command line.

Output streams are injectable so the commands can be tested without capturing
process-level file descriptors. Results go to stdout; logs and errors go to
stderr, so piping a command's output never mixes the two.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from pydantic import ValidationError

from cine_analyzer import __version__
from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
from cine_analyzer.application.errors import AdapterError, IngestError
from cine_analyzer.application.ingest import content_storage_key
from cine_analyzer.application.pipeline import SamplingStageResult
from cine_analyzer.application.timeline import summarize_timeline
from cine_analyzer.diagnostics import Diagnostic, exit_code_for, run_diagnostics
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.errors import SafeError
from cine_analyzer.domain.report import AnalysisReport
from cine_analyzer.domain.timeline import Timeline
from cine_analyzer.logging_setup import configure_logging, get_logger
from cine_analyzer.settings import Settings, load_settings

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

_NAME_COLUMN = 16
_STATUS_COLUMN = 13


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="cine-analyzer",
        description="Reproducible cinematography measurement with traceable evidence.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the package version and exit",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser(
        "doctor",
        help="report runtime capabilities without requiring them",
        description=(
            "Report what this installation can do. An optional capability that is "
            "missing is reported as unavailable with a reason and does not fail the command."
        ),
    )
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="stream a local file into the artifact store and record video identity",
    )
    ingest_parser.add_argument(
        "path",
        type=Path,
        help="local media path. A name that starts with '-' must be passed after --",
    )
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="ingest a local file and create or reuse an analysis identity",
    )
    analyze_parser.add_argument(
        "path",
        type=Path,
        help="local media path. A name that starts with '-' must be passed after --",
    )
    analyze_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="create or reuse analysis identity without running later stages",
    )
    analyze_parser.add_argument(
        "--through",
        choices=("identity", "sampling", "report"),
        default="identity",
        help="identity stops after analysis identity; sampling runs shots; report adds chromatics",
    )
    analyze_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the validated AnalysisReport JSON (implies --through report)",
    )
    analyze_parser.add_argument(
        "--spatial-backend",
        choices=("none", "fake"),
        default=None,
        help="override SpatialConfig.backend (default none: detector_not_installed)",
    )
    validate_parser = subparsers.add_parser(
        "validate-report",
        help="validate a local AnalysisReport JSON file against the public schema",
    )
    validate_parser.add_argument(
        "path",
        type=Path,
        help="path to a report JSON file. A name that starts with '-' must be passed after --",
    )
    inspect_parser = subparsers.add_parser(
        "inspect-timeline",
        help="summarize a report's tension-proxy timeline without filesystem paths",
    )
    inspect_parser.add_argument(
        "path",
        type=Path,
        help="path to a report JSON file. A name that starts with '-' must be passed after --",
    )
    serve_parser = subparsers.add_parser(
        "serve",
        help="run the HTTP control plane (no heavy analysis in this process)",
    )
    serve_parser.add_argument("--host", default=None, help="bind address (default CINE_API_HOST)")
    serve_parser.add_argument(
        "--port", type=int, default=None, help="bind port (default CINE_API_PORT)"
    )
    worker_parser = subparsers.add_parser(
        "worker",
        help="claim queued analyses and run sampling, report, and aggregate stages",
    )
    worker_parser.add_argument(
        "--once",
        action="store_true",
        help="claim at most one job then exit",
    )
    celery_parser = subparsers.add_parser(
        "celery-worker",
        help="run a Celery worker (CPU or GPU queues; requires the celery extra)",
    )
    celery_parser.add_argument(
        "--role",
        choices=("cpu", "gpu"),
        default="cpu",
        help="queue set and concurrency (gpu listens only to gpu_spatial)",
    )
    celery_parser.add_argument(
        "--queues",
        default=None,
        help="override the listen list (comma-separated queue names)",
    )
    openapi_parser = subparsers.add_parser(
        "export-openapi",
        help="write or check the public OpenAPI snapshot",
    )
    openapi_parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the snapshot does not match the live schema",
    )
    openapi_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="snapshot path (default tests/contract/api/openapi.json)",
    )
    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help="delete aged files under tmp or quarantine only",
    )
    cleanup_parser.add_argument("--prefix", choices=("tmp", "quarantine"), required=True)
    cleanup_parser.add_argument(
        "--max-age-ms",
        type=int,
        default=None,
        help="age threshold (default CINE_CLEANUP_MAX_AGE_MS)",
    )
    cleanup_parser.add_argument(
        "--canonical-key",
        default=None,
        help="delete one resolved canonical storage key instead of a prefix",
    )
    bench_parser = subparsers.add_parser(
        "benchmark",
        help="cold/warm CPU-core timings for the committed fixture manifest",
    )
    bench_parser.add_argument("--manifest", type=Path, required=True)
    bench_parser.add_argument("--output", type=Path, required=True)
    bench_parser.add_argument(
        "--profile",
        action="store_true",
        help="record top cProfile function names in the report",
    )
    validate_bench = subparsers.add_parser(
        "validate-benchmark",
        help="check a benchmark JSON report against the default config hash",
    )
    validate_bench.add_argument("path", type=Path)
    ready_parser = subparsers.add_parser(
        "worker-ready",
        help="check artifact-root and, for gpu, detector readiness",
    )
    ready_parser.add_argument("--role", choices=("cpu", "gpu"), default="cpu")
    critique_parser = subparsers.add_parser(
        "critique",
        help="optional evidence-bounded interpretation of a local AnalysisReport JSON",
    )
    critique_parser.add_argument(
        "path",
        type=Path,
        help="path to a report JSON file. A name that starts with '-' must be passed after --",
    )
    critique_parser.add_argument(
        "--backend",
        choices=("none", "fake", "openai"),
        default="fake",
        help="adapter override (default fake). Does not change measured metrics.",
    )
    return parser


def _render(diagnostic: Diagnostic) -> str:
    name = diagnostic.name.ljust(_NAME_COLUMN)
    status = diagnostic.status.value.ljust(_STATUS_COLUMN)
    return f"{name}{status}{diagnostic.detail}\n"


def _load_settings(stderr: TextIO, *, failure_context: str) -> Settings | None:
    try:
        return load_settings()
    except ValidationError as error:
        stderr.write(f"settings are invalid; {failure_context}\n{error}\n")
        return None


def build_services(settings: Settings) -> Any:
    """Lazy CLI wiring so ``serve`` and ``export-openapi`` do not load CV libraries."""
    from cine_analyzer.application.wiring import build_services as inner

    return inner(settings)


def _runtime(stderr: TextIO) -> tuple[Settings, Any] | None:
    settings = _load_settings(stderr, failure_context="the command was not started")
    if settings is None:
        return None
    configure_logging(settings, stream=stderr)
    return settings, build_services(settings)


def _write_json(stdout: TextIO, payload: Mapping[str, object]) -> None:
    stdout.write(json.dumps(payload, sort_keys=True) + "\n")


def _doctor(*, stdout: TextIO, stderr: TextIO) -> int:
    settings = _load_settings(stderr, failure_context="no capability check was run")
    if settings is None:
        return EXIT_FAILED

    configure_logging(settings, stream=stderr)
    diagnostics = run_diagnostics(settings)
    code = exit_code_for(diagnostics)

    stdout.write(f"cine-analyzer {__version__}\n")
    for diagnostic in diagnostics:
        stdout.write(_render(diagnostic))

    get_logger(__name__).info(
        "cli.doctor.completed",
        checks=len(diagnostics),
        unavailable=sum(1 for item in diagnostics if item.status.value == "unavailable"),
        exit_code=code,
    )
    return code


def _ingest(path: Path, *, stdout: TextIO, stderr: TextIO) -> int:
    runtime = _runtime(stderr)
    if runtime is None:
        return EXIT_FAILED
    _, services = runtime
    request_id = uuid4().hex
    try:
        result = services.ingest.execute(
            path,
            original_filename=path.name,
            config=AnalysisConfig(),
            request_id=request_id,
        )
    except IngestError as error:
        stderr.write(error.safe.model_dump_json() + "\n")
        return EXIT_FAILED
    finally:
        services.repository.close()
    _write_json(
        stdout,
        {
            "video_id": str(result.video.metadata.video_id),
            "content_sha256": result.video.metadata.content_sha256,
            "reused": result.reused,
        },
    )
    return EXIT_OK


def _analyze(
    path: Path,
    *,
    dry_run: bool,
    through: str,
    output: Path | None,
    spatial_backend: str | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    runtime = _runtime(stderr)
    if runtime is None:
        return EXIT_FAILED
    _, services = runtime
    request_id = uuid4().hex
    config = AnalysisConfig()
    if spatial_backend is not None:
        config = config.model_copy(
            update={"spatial": config.spatial.model_copy(update={"backend": spatial_backend})}
        )
    extra: dict[str, object] = {}
    try:
        ingested = services.ingest.execute(
            path,
            original_filename=path.name,
            config=config,
            request_id=request_id,
        )
        created = services.analyze.execute(
            video=ingested.video,
            config=config,
            request_id=request_id,
        )
        if through == "sampling":
            sampled = services.sampling.execute(
                video=ingested.video,
                analysis=created.analysis,
                config=config,
                request_id=request_id,
            )
            extra = _sampling_json(sampled)
        elif through == "report":
            reported = services.report.execute(
                video=ingested.video,
                analysis=created.analysis,
                config=config,
                request_id=request_id,
            )
            extra = _report_json(reported)
            if output is not None:
                _write_report_file(output, reported.report)
    except IngestError as error:
        stderr.write(error.safe.model_dump_json() + "\n")
        return EXIT_FAILED
    finally:
        services.repository.close()
    payload: dict[str, object] = {
        "analysis_id": str(created.analysis.analysis_id),
        "configuration_hash": created.configuration_hash,
        "dry_run": dry_run,
        "pipeline_version": created.analysis.pipeline_version,
        "reused": created.reused,
        "through": through,
        "video_id": str(created.analysis.video_id),
    }
    payload.update(extra)
    _write_json(stdout, payload)
    return EXIT_OK


def _sampling_json(result: SamplingStageResult) -> dict[str, object]:
    shots = [
        {
            "end_ms": shot.time_range.end_ms,
            "index": shot.index,
            "representative_sample_id": (
                None
                if shot.representative_sample_id is None
                else str(shot.representative_sample_id)
            ),
            "shot_id": str(shot.shot_id),
            "start_ms": shot.time_range.start_ms,
        }
        for shot in result.shot_set.shots
    ]
    samples = [
        {
            "artifact_id": None if item.image is None else str(item.image.artifact_id),
            "decoded_ms": item.decoded_ms,
            "purposes": [purpose.value for purpose in item.purposes],
            "requested_ms": item.requested_ms,
            "sample_id": str(item.sample_id),
            "shot_id": str(item.shot_id),
            "status": item.status.value,
            "storage_key": result.sample_keys.get(item.sample_id),
            "unavailable_reason": item.unavailable_reason,
        }
        for item in result.manifest.results
    ]
    return {
        "manifest_storage_key": result.manifest_key,
        "samples": samples,
        "shot_count": len(result.shot_set.shots),
        "shot_set_storage_key": result.shot_set_key,
        "shots": shots,
    }


def _report_json(result: object) -> dict[str, object]:
    from cine_analyzer.application.report import ReportStageResult

    if not isinstance(result, ReportStageResult):
        message = "report stage result is required"
        raise TypeError(message)
    sampling = _sampling_json(result.sampling)
    shots = []
    for item in result.report.shots:
        palette: list[str] = []
        lighting = None
        usable = None
        framing = None
        thirds = None
        if item.chromatic.value is not None:
            palette = [swatch.rgb.hex for swatch in item.chromatic.value.palette]
            lighting = item.chromatic.value.lighting_key.value
            usable = item.chromatic.value.usable_pixel_ratio
        if item.spatial.value is not None:
            framing = item.spatial.value.framing.value
            thirds = item.spatial.value.thirds_proximity_score
        global_motion = None
        residual_motion = None
        if item.temporal.value is not None:
            global_motion = item.temporal.value.global_motion_magnitude
            residual_motion = item.temporal.value.residual_motion_magnitude
        shots.append(
            {
                "end_ms": item.shot.time_range.end_ms,
                "framing": framing,
                "global_motion_magnitude": global_motion,
                "index": item.shot.index,
                "lighting_key": lighting,
                "palette": palette,
                "residual_motion_magnitude": residual_motion,
                "shot_id": str(item.shot.shot_id),
                "start_ms": item.shot.time_range.start_ms,
                "thirds_proximity": thirds,
                "usable_pixel_ratio": usable,
            }
        )
    sampling["shots"] = shots
    sampling["chromatic"] = result.report.availability.chromatic.value
    sampling["spatial"] = result.report.availability.spatial.value
    sampling["motion"] = result.report.availability.motion.value
    sampling["audio"] = result.report.availability.audio.value
    sampling["tension"] = result.report.availability.tension.value
    sampling["chromatics_storage_key"] = result.chromatics_key
    sampling["spatial_storage_key"] = result.spatial_key
    sampling["timeline_storage_key"] = result.timeline_key
    sampling["report_storage_key"] = result.report_key
    return sampling


def _write_report_file(path: Path, report: AnalysisReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _validate_report(path: Path, *, stdout: TextIO, stderr: TextIO) -> int:
    request_id = uuid4().hex
    try:
        payload = path.read_bytes()
    except OSError:
        stderr.write(
            SafeError(
                code="SCHEMA_INVALID",
                message="the report file could not be read",
                retryable=False,
                stage="report",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    try:
        report = AnalysisReport.model_validate_json(payload)
    except ValidationError:
        stderr.write(
            SafeError(
                code="SCHEMA_INVALID",
                message="the report does not match the public schema",
                retryable=False,
                stage="report",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    _write_json(
        stdout,
        {
            "analysis_id": str(report.analysis_id),
            "schema_version": report.schema_version,
            "shot_count": report.summary.shot_count,
            "valid": True,
        },
    )
    return EXIT_OK


def _inspect_timeline(path: Path, *, stdout: TextIO, stderr: TextIO) -> int:
    request_id = uuid4().hex
    settings = _load_settings(stderr, failure_context="the timeline was not inspected")
    if settings is None:
        return EXIT_FAILED
    try:
        payload = path.read_bytes()
    except OSError:
        stderr.write(
            SafeError(
                code="SCHEMA_INVALID",
                message="the report file could not be read",
                retryable=False,
                stage="report",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    try:
        report = AnalysisReport.model_validate_json(payload)
    except ValidationError:
        stderr.write(
            SafeError(
                code="SCHEMA_INVALID",
                message="the report does not match the public schema",
                retryable=False,
                stage="report",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    if report.timeline_artifact is None:
        stderr.write(
            SafeError(
                code="ARTIFACT_MISSING",
                message="the report does not include a timeline artifact",
                retryable=False,
                stage="report",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    store = FilesystemArtifactStore(settings.artifact_root)
    key = content_storage_key(report.timeline_artifact.sha256)
    try:
        timeline_bytes = store.local_path(key).read_bytes()
    except (AdapterError, OSError):
        stderr.write(
            SafeError(
                code="ARTIFACT_MISSING",
                message="the timeline artifact is not available",
                retryable=False,
                stage="report",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    try:
        timeline = Timeline.model_validate_json(timeline_bytes)
    except ValidationError:
        stderr.write(
            SafeError(
                code="SCHEMA_INVALID",
                message="the timeline does not match the public schema",
                retryable=False,
                stage="report",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    _write_json(stdout, summarize_timeline(timeline))
    return EXIT_OK


def _serve(*, host: str | None, port: int | None, stderr: TextIO) -> int:
    settings = _load_settings(stderr, failure_context="the API was not started")
    if settings is None:
        return EXIT_FAILED
    if settings.database_url is None:
        stderr.write("CINE_DATABASE_URL is required to serve the API\n")
        return EXIT_FAILED
    configure_logging(settings, stream=stderr)
    import uvicorn

    from cine_analyzer.api.app import create_app

    bound_host = settings.api_host if host is None else host
    bound_port = settings.api_port if port is None else port
    uvicorn.run(create_app(settings=settings), host=bound_host, port=bound_port)
    return EXIT_OK


def _worker(*, once: bool, stdout: TextIO, stderr: TextIO) -> int:
    from cine_analyzer.worker.runner import run_worker

    return run_worker(once=once, stdout=stdout, stderr=stderr)


def _celery_worker(*, role: str, queues: str | None, stdout: TextIO, stderr: TextIO) -> int:
    from cine_analyzer.worker.celery_worker import run_celery_worker

    del stdout
    return run_celery_worker(role=role, queues=queues, stderr=stderr)


def _export_openapi(*, check: bool, output: Path | None, stdout: TextIO, stderr: TextIO) -> int:
    from cine_analyzer.api.app import OPENAPI_SNAPSHOT, create_app

    schema = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    path = OPENAPI_SNAPSHOT if output is None else output
    if check:
        if not path.is_file() or path.read_text(encoding="utf-8") != schema:
            stderr.write("OpenAPI snapshot does not match the live schema\n")
            return EXIT_FAILED
        stdout.write("openapi snapshot ok\n")
        return EXIT_OK
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(schema, encoding="utf-8")
    stdout.write(str(path) + "\n")
    return EXIT_OK


def _cleanup(
    *,
    prefix: str,
    max_age_ms: int | None,
    canonical_key: str | None,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    settings = _load_settings(stderr, failure_context="cleanup was not started")
    if settings is None:
        return EXIT_FAILED
    from cine_analyzer.application.retention import delete_canonical_blob, purge_ephemeral

    try:
        if canonical_key is not None:
            delete_canonical_blob(settings.artifact_root, canonical_key)
            deleted = 1
        else:
            age = settings.cleanup_max_age_ms if max_age_ms is None else max_age_ms
            deleted = purge_ephemeral(settings.artifact_root, prefix, max_age_ms=age)
    except AdapterError as error:
        stderr.write(
            SafeError(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                stage="cleanup",
                request_id="cli-cleanup",
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    _write_json(stdout, {"deleted": deleted, "prefix": prefix})
    return EXIT_OK


def _benchmark(
    *,
    manifest: Path,
    output: Path,
    profile: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    settings = _load_settings(stderr, failure_context="benchmark was not started")
    if settings is None:
        return EXIT_FAILED
    configure_logging(settings, stream=stderr)
    from cine_analyzer.application.benchmark import load_manifest, run_benchmark
    from cine_analyzer.application.errors import IngestError

    repo_root = Path(__file__).resolve().parents[3]
    try:
        parsed = load_manifest(manifest)
        report = run_benchmark(
            parsed,
            repo_root=repo_root,
            work_root=output.parent / "benchmark-work",
            profile=profile,
        )
    except (OSError, ValueError, ValidationError) as error:
        stderr.write("the benchmark manifest could not be read\n")
        del error
        return EXIT_FAILED
    except IngestError as error:
        stderr.write(error.safe.model_dump_json() + "\n")
        return EXIT_FAILED
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json() + "\n", encoding="utf-8")
    stdout.write(str(output) + "\n")
    return EXIT_OK


def _validate_benchmark(path: Path, *, stdout: TextIO, stderr: TextIO) -> int:
    from cine_analyzer.application.benchmark import BenchmarkReport, validate_benchmark_report
    from cine_analyzer.domain.config import AnalysisConfig, canonical_hash

    try:
        report = BenchmarkReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        stderr.write("the benchmark report could not be validated\n")
        return EXIT_FAILED
    ok, reason = validate_benchmark_report(report, expected_hash=canonical_hash(AnalysisConfig()))
    if not ok:
        stderr.write(reason + "\n")
        return EXIT_FAILED
    stdout.write("benchmark report ok\n")
    return EXIT_OK


def _worker_ready(*, role: str, stdout: TextIO, stderr: TextIO) -> int:
    settings = _load_settings(stderr, failure_context="readiness was not checked")
    if settings is None:
        return EXIT_FAILED
    from cine_analyzer.worker.lifecycle import worker_is_ready

    ok, detail = worker_is_ready(settings, role=role)
    payload = {"status": "ok" if ok else "unavailable", "detail": detail, "role": role}
    _write_json(stdout, payload)
    return EXIT_OK if ok else EXIT_FAILED


def _critique(path: Path, *, backend: str, stdout: TextIO, stderr: TextIO) -> int:
    request_id = uuid4().hex
    settings = _load_settings(stderr, failure_context="the critique was not produced")
    if settings is None:
        return EXIT_FAILED
    try:
        payload = path.read_bytes()
    except OSError:
        stderr.write(
            SafeError(
                code="SCHEMA_INVALID",
                message="the report file could not be read",
                retryable=False,
                stage="critic",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    try:
        report = AnalysisReport.model_validate_json(payload)
    except ValidationError:
        stderr.write(
            SafeError(
                code="SCHEMA_INVALID",
                message="the report does not match the public schema",
                retryable=False,
                stage="critic",
                request_id=request_id,
            ).model_dump_json()
            + "\n"
        )
        return EXIT_FAILED
    from cine_analyzer.application.critic import build_critic, run_critique

    adapter = build_critic(settings, backend=backend)
    critique = run_critique(
        report, adapter=adapter, timeout_ms=settings.critic_timeout_ms, cache={}
    )
    _write_json(stdout, critique.model_dump(mode="json"))
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI and return a process exit code."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        out.write(f"cine-analyzer {__version__}\n")
        return EXIT_OK

    if args.command == "doctor":
        return _doctor(stdout=out, stderr=err)
    if args.command == "ingest":
        return _ingest(args.path, stdout=out, stderr=err)
    if args.command == "validate-report":
        return _validate_report(args.path, stdout=out, stderr=err)
    if args.command == "inspect-timeline":
        return _inspect_timeline(args.path, stdout=out, stderr=err)
    if args.command == "serve":
        return _serve(host=args.host, port=args.port, stderr=err)
    if args.command == "worker":
        return _worker(once=args.once, stdout=out, stderr=err)
    if args.command == "celery-worker":
        return _celery_worker(role=args.role, queues=args.queues, stdout=out, stderr=err)
    if args.command == "export-openapi":
        return _export_openapi(check=args.check, output=args.output, stdout=out, stderr=err)
    if args.command == "cleanup":
        return _cleanup(
            prefix=args.prefix,
            max_age_ms=args.max_age_ms,
            canonical_key=args.canonical_key,
            stdout=out,
            stderr=err,
        )
    if args.command == "benchmark":
        return _benchmark(
            manifest=args.manifest,
            output=args.output,
            profile=args.profile,
            stdout=out,
            stderr=err,
        )
    if args.command == "validate-benchmark":
        return _validate_benchmark(args.path, stdout=out, stderr=err)
    if args.command == "worker-ready":
        return _worker_ready(role=args.role, stdout=out, stderr=err)
    if args.command == "critique":
        return _critique(args.path, backend=args.backend, stdout=out, stderr=err)
    if args.command == "analyze":
        through = args.through
        output = args.output
        if output is not None and through == "identity":
            through = "report"
        if output is not None and through == "sampling":
            err.write("--output cannot be combined with --through sampling\n")
            return EXIT_USAGE
        if args.dry_run and through in {"sampling", "report"}:
            err.write(f"--dry-run cannot be combined with --through {through}\n")
            return EXIT_USAGE
        return _analyze(
            args.path,
            dry_run=args.dry_run,
            through=through,
            output=output,
            spatial_backend=args.spatial_backend,
            stdout=out,
            stderr=err,
        )

    parser.print_help(err)
    return EXIT_USAGE
