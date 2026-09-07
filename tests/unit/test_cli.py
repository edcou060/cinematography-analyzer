"""The two commands this phase ships, including how they refuse."""

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tests.factories import (
    ANALYSIS_ID,
    DIGEST,
    SAMPLE_ID,
    SHOT_ID,
    VIDEO_ID,
    make_artifact,
    make_availability,
    make_provenance,
    make_report,
    make_shot,
    make_shot_analysis,
    make_shot_set,
    make_spatial_value,
)
from tests.unit.application.fakes import video_record_from_bytes

from cine_analyzer import __version__
from cine_analyzer.adapters.persistence.sqlite import SqliteAnalysisRepository
from cine_analyzer.api.app import create_app
from cine_analyzer.application.analyze import CreateAnalysisResult
from cine_analyzer.application.errors import ingest_error
from cine_analyzer.application.ingest import IngestResult
from cine_analyzer.application.pipeline import SamplingStageResult
from cine_analyzer.application.report import ReportStageResult
from cine_analyzer.application.wiring import Services
from cine_analyzer.cli.main import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    _report_json,
    build_services,
    main,
)
from cine_analyzer.domain.chromatics import ChromaticMeasurement
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleRequest,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
)
from cine_analyzer.domain.report import StageAvailability
from cine_analyzer.domain.spatial import SpatialMeasurement
from cine_analyzer.domain.temporal import TemporalMeasurement
from cine_analyzer.domain.types import SCHEMA_VERSION, MetricStatus
from cine_analyzer.ports.ingestion import AnalysisRecord
from cine_analyzer.settings import Settings
from cine_analyzer.worker import runner as worker_runner

EXPECTED_VERSION_LINE = f"cine-analyzer {__version__}\n"


class _NoSampling:
    def execute(self, **_kwargs: object) -> object:
        message = "sampling should not run"
        raise AssertionError(message)


class _NoReport:
    def execute(self, **_kwargs: object) -> object:
        message = "report should not run"
        raise AssertionError(message)


def test_version_flag_prints_the_version_and_succeeds() -> None:
    stdout = io.StringIO()

    code = main(["--version"], stdout=stdout, stderr=io.StringIO())

    assert code == EXIT_OK
    assert stdout.getvalue() == EXPECTED_VERSION_LINE


def test_python_dash_m_entry_point_reports_the_same_version() -> None:
    completed = subprocess.run(  # fixed argv, no shell, no user input
        [sys.executable, "-m", "cine_analyzer", "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert completed.returncode == EXIT_OK
    assert completed.stdout == EXPECTED_VERSION_LINE


def test_the_console_script_is_installed_and_reports_the_same_version() -> None:
    executable = shutil.which("cine-analyzer")
    if executable is None:
        pytest.skip("console script is not on PATH outside a synced environment")

    completed = subprocess.run(  # resolved path, no shell, no user input
        [executable, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert completed.returncode == EXIT_OK
    assert completed.stdout == EXPECTED_VERSION_LINE


def test_doctor_reports_every_capability_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _binary: "/usr/bin/" + _binary)
    stdout = io.StringIO()

    code = main(["doctor"], stdout=stdout, stderr=io.StringIO())

    rendered = stdout.getvalue()
    assert code == EXIT_OK
    assert rendered.startswith(EXPECTED_VERSION_LINE)
    for name in ("python_runtime", "settings", "ffmpeg", "ffprobe", "critic"):
        assert name in rendered


def test_doctor_succeeds_while_reporting_ffmpeg_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """doctor succeeds when ffmpeg is missing; absence is a diagnosis, not a failure."""
    monkeypatch.setattr("shutil.which", lambda _binary: None)
    stdout = io.StringIO()

    code = main(["doctor"], stdout=stdout, stderr=io.StringIO())

    assert code == EXIT_OK
    assert "ffmpeg          unavailable" in stdout.getvalue()
    assert "first required by Phase 03 ingestion" in stdout.getvalue()


def test_doctor_emits_a_structured_log_event_to_stderr() -> None:
    stderr = io.StringIO()

    main(["doctor"], stdout=io.StringIO(), stderr=stderr)

    assert '"event": "cli.doctor.completed"' in stderr.getvalue()


def test_doctor_keeps_results_on_stdout_and_logs_on_stderr() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    main(["doctor"], stdout=stdout, stderr=stderr)

    assert "python_runtime" in stdout.getvalue()
    assert "python_runtime" not in stderr.getvalue()


def test_doctor_reports_a_configuration_error_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CINE_LOG_LEVEL", "chatty")
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(["doctor"], stdout=stdout, stderr=stderr)

    assert code == EXIT_FAILED
    assert stdout.getvalue() == ""
    assert "settings are invalid" in stderr.getvalue()
    assert "log_level" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_no_arguments_prints_usage_to_stderr_and_reports_misuse() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main([], stdout=stdout, stderr=stderr)

    assert code == EXIT_USAGE
    assert stdout.getvalue() == ""
    assert "usage: cine-analyzer" in stderr.getvalue()


@pytest.mark.parametrize("argv", [["--nonsense"], ["measure"], ["--vers"]])
def test_an_unrecognised_argument_exits_with_the_conventional_usage_code(
    argv: list[str],
) -> None:
    """``allow_abbrev=False`` means ``--vers`` is a mistake, not a shorthand for ``--version``."""
    with pytest.raises(SystemExit) as caught:
        main(argv, stdout=io.StringIO(), stderr=io.StringIO())

    assert caught.value.code == EXIT_USAGE


def test_ingest_without_a_path_is_usage() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["ingest"], stdout=io.StringIO(), stderr=io.StringIO())

    assert caught.value.code == EXIT_USAGE


def test_ingest_writes_identity_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert original_filename == "clip.mp4"
            assert request_id
            assert source.name == "clip.mp4"
            assert config is not None
            return IngestResult(video=video, reused=False)

    class _Analyze:
        def execute(self, *, video: object, config: object, request_id: str) -> object:
            message = f"analyze should not run {video!r} {config!r} {request_id}"
            raise AssertionError(message)

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stdout = io.StringIO()
    try:
        code = main(["ingest", "clip.mp4"], stdout=stdout, stderr=io.StringIO())
    finally:
        repo.close()

    assert code == EXIT_OK
    payload = json.loads(stdout.getvalue())
    assert payload["video_id"] == str(video.metadata.video_id)
    assert payload["reused"] is False
    assert payload["content_sha256"] == video.metadata.content_sha256


def test_analyze_dry_run_writes_identity_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    analysis = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="f" * 64,
        state=AnalysisState.QUEUED,
    )
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert source.name == "clip.mp4"
            assert original_filename == "clip.mp4"
            assert config is not None
            assert request_id
            return IngestResult(video=video, reused=True)

    class _Analyze:
        def execute(
            self, *, video: object, config: object, request_id: str
        ) -> CreateAnalysisResult:
            assert video is not None
            assert config is not None
            assert request_id
            return CreateAnalysisResult(analysis=analysis, reused=False, configuration_hash=DIGEST)

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stdout = io.StringIO()
    try:
        code = main(["analyze", "clip.mp4", "--dry-run"], stdout=stdout, stderr=io.StringIO())
    finally:
        repo.close()

    assert code == EXIT_OK
    payload = json.loads(stdout.getvalue())
    assert payload["analysis_id"] == str(ANALYSIS_ID)
    assert payload["dry_run"] is True
    assert payload["reused"] is False
    assert payload["pipeline_version"] == "0.1.0"
    assert payload["through"] == "identity"


def test_analyze_without_dry_run_still_only_creates_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    analysis = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="f" * 64,
        state=AnalysisState.QUEUED,
    )
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert source.name == "clip.mp4"
            assert original_filename == "clip.mp4"
            assert config is not None
            assert request_id
            return IngestResult(video=video, reused=True)

    class _Analyze:
        def execute(
            self, *, video: object, config: object, request_id: str
        ) -> CreateAnalysisResult:
            assert video is not None
            assert config is not None
            assert request_id
            return CreateAnalysisResult(analysis=analysis, reused=True, configuration_hash=DIGEST)

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stdout = io.StringIO()
    try:
        code = main(["analyze", "clip.mp4"], stdout=stdout, stderr=io.StringIO())
    finally:
        repo.close()

    payload = json.loads(stdout.getvalue())
    assert code == EXIT_OK
    assert payload["dry_run"] is False
    assert payload["reused"] is True


def test_ingest_safe_error_is_json_on_stderr_without_a_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> None:
            assert source.name == "clip.mp4"
            assert original_filename
            assert config is not None
            raise ingest_error(
                "MEDIA_CORRUPT",
                "the media file could not be probed",
                request_id=request_id,
                retryable=False,
            )

    class _Analyze:
        def execute(self, *, video: object, config: object, request_id: str) -> None:
            message = f"unused {video!r} {config!r} {request_id}"
            raise AssertionError(message)

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        code = main(["ingest", "/secret/path/clip.mp4"], stdout=stdout, stderr=stderr)
    finally:
        repo.close()

    assert code == EXIT_FAILED
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue().splitlines()[-1])
    assert payload["code"] == "MEDIA_CORRUPT"
    assert "/secret/path" not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_analyze_safe_error_is_json_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> None:
            assert source.name == "clip.mp4"
            assert original_filename
            assert config is not None
            raise ingest_error(
                "MEDIA_TOO_LARGE",
                "upload exceeds the configured size limit",
                request_id=request_id,
                retryable=False,
            )

    class _Analyze:
        def execute(self, *, video: object, config: object, request_id: str) -> None:
            message = f"unused {video!r} {config!r} {request_id}"
            raise AssertionError(message)

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stderr = io.StringIO()
    try:
        code = main(["analyze", "clip.mp4", "--dry-run"], stdout=io.StringIO(), stderr=stderr)
    finally:
        repo.close()

    assert code == EXIT_FAILED
    assert json.loads(stderr.getvalue().splitlines()[-1])["code"] == "MEDIA_TOO_LARGE"


def test_ingest_reports_invalid_settings_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CINE_LOG_LEVEL", "chatty")
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(["ingest", "clip.mp4"], stdout=stdout, stderr=stderr)

    assert code == EXIT_FAILED
    assert stdout.getvalue() == ""
    assert "settings are invalid" in stderr.getvalue()
    assert "the command was not started" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_analyze_reports_invalid_settings_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CINE_LOG_LEVEL", "chatty")
    code = main(["analyze", "clip.mp4"], stdout=io.StringIO(), stderr=io.StringIO())
    assert code == EXIT_FAILED


def test_dry_run_cannot_run_sampling() -> None:
    stderr = io.StringIO()
    code = main(
        ["analyze", "clip.mp4", "--dry-run", "--through", "sampling"],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_USAGE
    assert "--dry-run cannot be combined with --through sampling" in stderr.getvalue()


def test_analyze_through_sampling_lists_shots_and_evidence_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    analysis = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="f" * 64,
        state=AnalysisState.QUEUED,
    )
    shot_set = make_shot_set(
        shots=(
            make_shot(index=0, start_ms=0, end_ms=2000, representative_sample_id=SAMPLE_ID),
            make_shot(index=1, start_ms=2000, end_ms=4000),
        )
    )
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        requests=(
            SampleRequest(
                sample_id=SAMPLE_ID,
                shot_id=SHOT_ID,
                requested_ms=1000,
                purposes=(SamplePurpose.EVIDENCE,),
            ),
        ),
    )
    manifest = SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(
            SampleResult(
                sample_id=SAMPLE_ID,
                shot_id=SHOT_ID,
                requested_ms=1000,
                decoded_ms=1040,
                frame_index=26,
                purposes=(SamplePurpose.EVIDENCE,),
                status=SampleStatus.DECODED,
                image=make_artifact(kind="evidence_frame", media_type="image/jpeg"),
            ),
        ),
    )
    sampled = SamplingStageResult(
        shot_set=shot_set,
        plan=plan,
        manifest=manifest,
        shot_set_key="analyses/aaa/shot_set.json",
        manifest_key="analyses/aaa/sampling_manifest.json",
        debug_stats_key=None,
        sample_keys={SAMPLE_ID: "aa/" + "a" * 64},
    )
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert source.name == "clip.mp4"
            assert original_filename
            assert config is not None
            assert request_id
            return IngestResult(video=video, reused=True)

    class _Analyze:
        def execute(
            self, *, video: object, config: object, request_id: str
        ) -> CreateAnalysisResult:
            assert video is not None
            assert config is not None
            assert request_id
            return CreateAnalysisResult(analysis=analysis, reused=True, configuration_hash=DIGEST)

    class _Sampling:
        def execute(
            self, *, video: object, analysis: object, config: object, request_id: str
        ) -> SamplingStageResult:
            assert video is not None
            assert analysis is not None
            assert config is not None
            assert request_id
            return sampled

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_Sampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stdout = io.StringIO()
    try:
        code = main(
            ["analyze", "clip.mp4", "--through", "sampling"],
            stdout=stdout,
            stderr=io.StringIO(),
        )
    finally:
        repo.close()

    assert code == EXIT_OK
    payload = json.loads(stdout.getvalue())
    assert payload["through"] == "sampling"
    assert payload["shot_count"] == 2
    assert payload["shots"][0]["start_ms"] == 0
    assert payload["shots"][0]["end_ms"] == 2000
    assert payload["samples"][0]["sample_id"] == str(SAMPLE_ID)
    assert payload["samples"][0]["decoded_ms"] == 1040
    assert payload["samples"][0]["requested_ms"] == 1000
    assert payload["samples"][0]["storage_key"] == "aa/" + "a" * 64
    assert "scene" not in json.dumps(payload)


def test_analyze_sampling_safe_error_is_json_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    analysis = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="f" * 64,
        state=AnalysisState.QUEUED,
    )
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert source.name == "clip.mp4"
            assert original_filename
            assert config is not None
            assert request_id
            return IngestResult(video=video, reused=True)

    class _Analyze:
        def execute(
            self, *, video: object, config: object, request_id: str
        ) -> CreateAnalysisResult:
            assert video is not None
            assert config is not None
            assert request_id
            return CreateAnalysisResult(analysis=analysis, reused=True, configuration_hash=DIGEST)

    class _Sampling:
        def execute(self, **_kwargs: object) -> SamplingStageResult:
            raise ingest_error(
                "SHOT_FAILED",
                "shot detection failed",
                request_id=_kwargs["request_id"],  # type: ignore[index]
                retryable=True,
                stage="shots",
            )

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_Sampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stderr = io.StringIO()
    try:
        code = main(
            ["analyze", "clip.mp4", "--through", "sampling"],
            stdout=io.StringIO(),
            stderr=stderr,
        )
    finally:
        repo.close()

    assert code == EXIT_FAILED
    payload = json.loads(stderr.getvalue().splitlines()[-1])
    assert payload["code"] == "SHOT_FAILED"
    assert payload["stage"] == "shots"


def test_dry_run_cannot_write_a_report() -> None:
    stderr = io.StringIO()
    code = main(
        ["analyze", "clip.mp4", "--dry-run", "--output", "build/report.json"],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_USAGE
    assert "--dry-run cannot be combined with --through report" in stderr.getvalue()


def test_output_cannot_combine_with_sampling() -> None:
    stderr = io.StringIO()
    code = main(
        ["analyze", "clip.mp4", "--through", "sampling", "--output", "out.json"],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_USAGE
    assert "--output cannot be combined with --through sampling" in stderr.getvalue()


def test_analyze_output_writes_a_validated_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    analysis = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="f" * 64,
        state=AnalysisState.QUEUED,
    )
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=4000),))
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        requests=(),
    )
    manifest = SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(),
    )
    sampled = SamplingStageResult(
        shot_set=shot_set,
        plan=plan,
        manifest=manifest,
        shot_set_key="analyses/aaa/shot_set.json",
        manifest_key="analyses/aaa/sampling_manifest.json",
        debug_stats_key=None,
        sample_keys={},
    )
    ok_spatial = SpatialMeasurement(
        status=MetricStatus.OK,
        value=make_spatial_value(),
        method=make_provenance(),
    )
    shot = make_shot_analysis().model_copy(update={"spatial": ok_spatial})
    report = make_report(
        shots=(shot,),
        availability=make_availability(spatial=StageAvailability.COMPLETE),
    )
    reported = ReportStageResult(
        sampling=sampled,
        report=report,
        report_key="analyses/aaa/report.json",
        chromatics_key="analyses/aaa/chromatics.json",
        spatial_key="analyses/aaa/spatial.json",
        timeline_key="analyses/aaa/timeline.json",
    )
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")
    destination = tmp_path / "out" / "report.json"

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert source.name == "clip.mp4"
            assert original_filename
            assert config is not None
            assert request_id
            return IngestResult(video=video, reused=True)

    class _Analyze:
        def execute(
            self, *, video: object, config: object, request_id: str
        ) -> CreateAnalysisResult:
            assert video is not None
            assert config is not None
            assert request_id
            return CreateAnalysisResult(analysis=analysis, reused=True, configuration_hash=DIGEST)

    class _Report:
        def execute(self, **_kwargs: object) -> ReportStageResult:
            return reported

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_Report(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stdout = io.StringIO()
    try:
        code = main(
            ["analyze", "clip.mp4", "--output", str(destination)],
            stdout=stdout,
            stderr=io.StringIO(),
        )
    finally:
        repo.close()

    assert code == EXIT_OK
    payload = json.loads(stdout.getvalue())
    assert payload["through"] == "report"
    assert payload["chromatic"] == "COMPLETE"
    assert payload["spatial"] == "COMPLETE"
    assert payload["motion"] == "UNAVAILABLE"
    assert payload["audio"] == "UNAVAILABLE"
    assert payload["tension"] == "UNAVAILABLE"
    assert payload["timeline_storage_key"] == "analyses/aaa/timeline.json"
    assert payload["spatial_storage_key"] == "analyses/aaa/spatial.json"
    assert payload["shots"][0]["framing"] == "MEDIUM_ESTIMATE"
    assert payload["shots"][0]["thirds_proximity"] == 0.5
    assert destination.is_file()
    assert "ESTIMATE" in destination.read_text(encoding="utf-8")


def test_validate_report_accepts_a_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(make_report().model_dump_json(), encoding="utf-8")
    stdout = io.StringIO()
    code = main(["validate-report", str(path)], stdout=stdout, stderr=io.StringIO())
    assert code == EXIT_OK
    payload = json.loads(stdout.getvalue())
    assert payload["valid"] is True
    assert payload["shot_count"] == 1


def test_validate_report_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("{}", encoding="utf-8")
    stderr = io.StringIO()
    code = main(["validate-report", str(path)], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert json.loads(stderr.getvalue().splitlines()[-1])["code"] == "SCHEMA_INVALID"


def test_validate_report_rejects_a_missing_file(tmp_path: Path) -> None:
    stderr = io.StringIO()
    code = main(
        ["validate-report", str(tmp_path / "missing.json")],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == EXIT_FAILED
    payload = json.loads(stderr.getvalue().splitlines()[-1])
    assert payload["code"] == "SCHEMA_INVALID"
    assert "missing.json" not in payload["message"]


def test_critique_fake_and_failures(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(make_report().model_dump_json(), encoding="utf-8")
    stdout = io.StringIO()
    code = main(["critique", str(path), "--backend", "fake"], stdout=stdout, stderr=io.StringIO())
    assert code == EXIT_OK
    payload = json.loads(stdout.getvalue())
    assert payload["status"] == "OK"
    assert payload["text"]
    none = io.StringIO()
    assert main(
        ["critique", str(path), "--backend", "none"], stdout=none, stderr=io.StringIO()
    ) == (EXIT_OK)
    assert json.loads(none.getvalue())["status"] == "NOT_COMPUTED"
    stderr = io.StringIO()
    assert (
        main(
            ["critique", str(tmp_path / "missing.json"), "--backend", "fake"],
            stdout=io.StringIO(),
            stderr=stderr,
        )
        == EXIT_FAILED
    )
    assert "missing.json" not in json.loads(stderr.getvalue().splitlines()[-1])["message"]
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    invalid = io.StringIO()
    assert (
        main(["critique", str(bad), "--backend", "fake"], stdout=io.StringIO(), stderr=invalid)
        == EXIT_FAILED
    )
    assert json.loads(invalid.getvalue().splitlines()[-1])["code"] == "SCHEMA_INVALID"


def test_critique_rejects_invalid_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CINE_LOG_LEVEL", "nope")
    path = tmp_path / "report.json"
    path.write_text(make_report().model_dump_json(), encoding="utf-8")
    stderr = io.StringIO()
    code = main(["critique", str(path), "--backend", "fake"], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert "settings are invalid" in stderr.getvalue()


def test_analyze_through_report_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    analysis = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="f" * 64,
        state=AnalysisState.QUEUED,
    )
    shot_set = make_shot_set(shots=(make_shot(index=0, start_ms=0, end_ms=4000),))
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        requests=(),
    )
    manifest = SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(),
    )
    sampled = SamplingStageResult(
        shot_set=shot_set,
        plan=plan,
        manifest=manifest,
        shot_set_key="analyses/aaa/shot_set.json",
        manifest_key="analyses/aaa/sampling_manifest.json",
        debug_stats_key=None,
        sample_keys={},
    )
    insufficient = ChromaticMeasurement(
        status=MetricStatus.INSUFFICIENT_DATA,
        value=None,
        reason_code="chromatic_letterbox_insufficient",
        method=make_provenance(),
    )
    missing_temporal = TemporalMeasurement(
        status=MetricStatus.NOT_COMPUTED,
        value=None,
        reason_code="motion_not_computed",
        method=make_provenance(),
    )
    shot = make_shot_analysis().model_copy(
        update={"chromatic": insufficient, "temporal": missing_temporal}
    )
    report = make_report(
        shots=(shot,),
        availability=make_availability(chromatic=StageAvailability.UNAVAILABLE),
    )
    reported = ReportStageResult(
        sampling=sampled,
        report=report,
        report_key="analyses/aaa/report.json",
        chromatics_key="analyses/aaa/chromatics.json",
        spatial_key="analyses/aaa/spatial.json",
        timeline_key="analyses/aaa/timeline.json",
    )
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert source.name == "clip.mp4"
            assert original_filename
            assert config is not None
            assert request_id
            return IngestResult(video=video, reused=True)

    class _Analyze:
        def execute(
            self, *, video: object, config: object, request_id: str
        ) -> CreateAnalysisResult:
            assert video is not None
            assert config is not None
            assert request_id
            return CreateAnalysisResult(analysis=analysis, reused=True, configuration_hash=DIGEST)

    class _Report:
        def execute(self, **_kwargs: object) -> ReportStageResult:
            return reported

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_Report(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    stdout = io.StringIO()
    try:
        code = main(
            ["analyze", "clip.mp4", "--through", "report"],
            stdout=stdout,
            stderr=io.StringIO(),
        )
    finally:
        repo.close()

    assert code == EXIT_OK
    payload = json.loads(stdout.getvalue())
    assert payload["through"] == "report"
    assert payload["shots"][0]["lighting_key"] is None
    assert payload["shots"][0]["palette"] == []
    assert payload["shots"][0]["framing"] is None
    assert payload["shots"][0]["thirds_proximity"] is None
    assert payload["shots"][0]["global_motion_magnitude"] is None
    assert payload["shots"][0]["residual_motion_magnitude"] is None


def test_analyze_forwards_spatial_backend_into_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = video_record_from_bytes(b"cli-clip")
    analysis = AnalysisRecord(
        analysis_id=ANALYSIS_ID,
        video_id=video.metadata.video_id,
        configuration_hash=DIGEST,
        pipeline_version="0.1.0",
        analysis_key="f" * 64,
        state=AnalysisState.QUEUED,
    )
    repo = SqliteAnalysisRepository(tmp_path / "state.sqlite")
    seen: dict[str, object] = {}

    class _Ingest:
        def execute(
            self, source: Path, *, original_filename: str, config: object, request_id: str
        ) -> IngestResult:
            assert source.name == "clip.mp4"
            assert original_filename
            assert isinstance(config, AnalysisConfig)
            seen["backend"] = config.spatial.backend
            seen["hash"] = config.hash()
            assert request_id
            return IngestResult(video=video, reused=True)

    class _Analyze:
        def execute(
            self, *, video: object, config: object, request_id: str
        ) -> CreateAnalysisResult:
            assert video is not None
            assert isinstance(config, AnalysisConfig)
            assert config.spatial.backend == seen["backend"]
            assert request_id
            return CreateAnalysisResult(analysis=analysis, reused=True, configuration_hash=DIGEST)

    def fake_build(_settings: object) -> Services:
        return Services(
            ingest=_Ingest(),
            analyze=_Analyze(),
            sampling=_NoSampling(),
            report=_NoReport(),
            repository=repo,
        )  # type: ignore[arg-type]

    monkeypatch.setattr("cine_analyzer.cli.main.build_services", fake_build)
    try:
        code = main(
            ["analyze", "clip.mp4", "--spatial-backend", "fake"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    finally:
        repo.close()

    assert code == EXIT_OK
    assert seen["backend"] == "fake"
    assert seen["hash"] != AnalysisConfig().hash()


def test_serve_requires_database_url() -> None:
    stderr = io.StringIO()
    code = main(["serve"], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert "CINE_DATABASE_URL" in stderr.getvalue()


def test_serve_starts_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_DATABASE_URL", "postgresql+pg8000://cine:@127.0.0.1:5432/cine")
    seen: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        seen["host"] = host
        seen["port"] = port
        seen["app"] = app

    monkeypatch.setattr("uvicorn.run", fake_run)
    code = main(
        ["serve", "--host", "127.0.0.1", "--port", "9001"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 9001
    defaults = main(["serve"], stdout=io.StringIO(), stderr=io.StringIO())
    assert defaults == EXIT_OK
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8000
    monkeypatch.setenv("CINE_LOG_LEVEL", "chatty")
    invalid = main(["serve"], stdout=io.StringIO(), stderr=io.StringIO())
    assert invalid == EXIT_FAILED


def test_worker_without_database_url_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    stderr = io.StringIO()
    code = main(["worker", "--once"], stdout=io.StringIO(), stderr=stderr)
    assert code == EXIT_FAILED
    assert "CINE_DATABASE_URL" in stderr.getvalue()

    def _ok_worker(**_kwargs: object) -> int:
        return EXIT_OK

    monkeypatch.setattr(worker_runner, "run_worker", _ok_worker)
    delegated = main(["worker", "--once"], stdout=io.StringIO(), stderr=io.StringIO())
    assert delegated == EXIT_OK


def test_celery_worker_cli_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _ok(*, role: str, queues: str | None, stderr: object) -> int:
        seen.append(role)
        del queues, stderr
        return EXIT_OK

    monkeypatch.setattr("cine_analyzer.worker.celery_worker.run_celery_worker", _ok)
    code = main(["celery-worker", "--role", "gpu"], stdout=io.StringIO(), stderr=io.StringIO())
    assert code == EXIT_OK
    assert seen == ["gpu"]


def test_export_openapi_writes_and_checks(tmp_path: Path) -> None:
    snapshot = tmp_path / "openapi.json"
    schema = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    stdout = io.StringIO()
    code = main(
        ["export-openapi", "--output", str(snapshot)],
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    assert snapshot.read_text(encoding="utf-8") == schema
    ok = main(
        ["export-openapi", "--check", "--output", str(snapshot)],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert ok == EXIT_OK
    snapshot.write_text("nope\n", encoding="utf-8")
    failed = main(
        ["export-openapi", "--check", "--output", str(snapshot)],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert failed == EXIT_FAILED


def test_cli_build_services_imports_wiring(tmp_path: Path) -> None:
    settings = Settings(artifact_root=tmp_path / "art", state_path=tmp_path / "state.sqlite")
    services = build_services(settings)
    assert services.ingest is not None


def test_report_json_rejects_unknown_results() -> None:
    with pytest.raises(TypeError):
        _report_json(object())


def test_cleanup_benchmark_and_worker_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(artifact_root=tmp_path / "art")
    (settings.artifact_root / "tmp").mkdir(parents=True)
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(settings.artifact_root))
    stdout = io.StringIO()
    code = main(
        ["cleanup", "--prefix", "tmp", "--max-age-ms", "0"],
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    assert json.loads(stdout.getvalue())["deleted"] == 0

    from hashlib import sha256

    from cine_analyzer.adapters.artifacts.filesystem import FilesystemArtifactStore
    from cine_analyzer.application.ingest import content_storage_key

    digest = sha256(b"kept").hexdigest()
    key = content_storage_key(digest)
    FilesystemArtifactStore(settings.artifact_root).put_bytes(b"kept", storage_key=key)
    canonical_out = io.StringIO()
    canonical = main(
        ["cleanup", "--prefix", "tmp", "--canonical-key", key],
        stdout=canonical_out,
        stderr=io.StringIO(),
    )
    assert canonical == EXIT_OK
    assert json.loads(canonical_out.getvalue())["deleted"] == 1

    default_age = main(
        ["cleanup", "--prefix", "quarantine"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert default_age == EXIT_OK

    failed = io.StringIO()
    bad = main(
        ["cleanup", "--prefix", "tmp", "--canonical-key", "../nope"],
        stdout=io.StringIO(),
        stderr=failed,
    )
    assert bad == EXIT_FAILED
    assert "ARTIFACT_INVALID_KEY" in failed.getvalue()

    missing = main(
        [
            "benchmark",
            "--manifest",
            str(tmp_path / "nope.yaml"),
            "--output",
            str(tmp_path / "out.json"),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert missing == EXIT_FAILED

    invalid_report = tmp_path / "bench.json"
    invalid_report.write_text("{}", encoding="utf-8")
    invalid = main(
        ["validate-benchmark", str(invalid_report)],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert invalid == EXIT_FAILED

    ready_out = io.StringIO()
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path / "ready-root"))
    ready = main(
        ["worker-ready", "--role", "cpu"],
        stdout=ready_out,
        stderr=io.StringIO(),
    )
    assert ready == EXIT_OK
    assert json.loads(ready_out.getvalue())["status"] == "ok"

    monkeypatch.setenv("CINE_LOG_LEVEL", "nope")
    settings_failed = main(
        ["cleanup", "--prefix", "tmp"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert settings_failed == EXIT_FAILED
    bench_settings = main(
        ["benchmark", "--manifest", str(tmp_path / "m.yaml"), "--output", str(tmp_path / "o.json")],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert bench_settings == EXIT_FAILED
    ready_settings = main(
        ["worker-ready"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert ready_settings == EXIT_FAILED


def test_validate_benchmark_and_gpu_worker_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cine_analyzer.application.benchmark import (
        BenchmarkClipResult,
        BenchmarkReport,
        BenchmarkRun,
    )
    from cine_analyzer.domain.config import AnalysisConfig, canonical_hash
    from cine_analyzer.worker.lifecycle import reset_gpu_detector

    hashed = canonical_hash(AnalysisConfig())
    run = BenchmarkRun(
        wall_ms=1,
        rss_raw=1,
        rtf_milli=1,
        jpeg_reads=1,
        jpeg_hits=0,
        config_hash=hashed,
        pipeline_version="0.1.0",
        golden_status="pass",
        duration_ms=1000,
    )
    report = BenchmarkReport(
        schema_version="1.0",
        profile="cpu_core",
        commit="dev",
        hardware="test",
        pipeline_version="0.1.0",
        configuration_hash=hashed,
        jpeg_cache="on",
        clips=(BenchmarkClipResult(clip_id="a", relative_path="x", cold=run, warm=run),),
    )
    path = tmp_path / "ok.json"
    path.write_text(report.model_dump_json(), encoding="utf-8")
    stdout = io.StringIO()
    assert main(["validate-benchmark", str(path)], stdout=stdout, stderr=io.StringIO()) == EXIT_OK
    assert "ok" in stdout.getvalue()

    bad_hash = report.model_copy(update={"configuration_hash": "0" * 64})
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(bad_hash.model_dump_json(), encoding="utf-8")
    assert (
        main(["validate-benchmark", str(bad_path)], stdout=io.StringIO(), stderr=io.StringIO())
        == EXIT_FAILED
    )

    reset_gpu_detector()
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path / "gpu-root"))
    monkeypatch.setenv("CINE_SPATIAL_WORKER_BACKEND", "ultralytics")
    gpu = main(["worker-ready", "--role", "gpu"], stdout=io.StringIO(), stderr=io.StringIO())
    assert gpu == EXIT_FAILED
    reset_gpu_detector()

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "profile": "cpu_core",
                "clips": [{"id": "x", "path": "missing.mp4", "required": True}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CINE_SPATIAL_WORKER_BACKEND", raising=False)
    monkeypatch.setenv("CINE_ARTIFACT_ROOT", str(tmp_path / "bench-art"))
    out = tmp_path / "build" / "benchmark.json"
    skip_code = main(
        ["benchmark", "--manifest", str(manifest), "--output", str(out), "--profile"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert skip_code == EXIT_OK
    assert out.is_file()

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise ingest_error("MEDIA_CORRUPT", "clip failed", request_id="bench", retryable=False)

    monkeypatch.setattr("cine_analyzer.application.benchmark.run_benchmark", _boom)
    ingest_fail = io.StringIO()
    ingest_code = main(
        ["benchmark", "--manifest", str(manifest), "--output", str(tmp_path / "fail.json")],
        stdout=io.StringIO(),
        stderr=ingest_fail,
    )
    assert ingest_code == EXIT_FAILED
    assert "MEDIA_CORRUPT" in ingest_fail.getvalue()
