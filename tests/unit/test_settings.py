"""The settings boundary: defaults, overrides, and every way it should refuse."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from cine_analyzer.settings import Settings, load_settings


def test_defaults_are_usable_without_any_environment_variable() -> None:
    settings = load_settings()

    assert settings.environment == "local"
    assert settings.service_name == "cine-analyzer"
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.ffmpeg_binary == "ffmpeg"
    assert settings.ffprobe_binary == "ffprobe"
    assert settings.ffprobe_timeout_ms == 30_000
    assert settings.ffmpeg_timeout_ms == 30_000
    assert settings.ffmpeg_max_stdout_bytes == 50_000_000
    assert settings.ingest_chunk_bytes == 65_536
    assert settings.artifact_root == Path("var/artifacts")
    assert settings.state_path == Path("var/state.sqlite")
    assert settings.database_url is None
    assert settings.lease_ttl_ms == 120_000
    assert settings.worker_poll_ms == 500
    assert settings.worker_id == "local-worker"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.api_public_url == "http://127.0.0.1:8000"
    assert settings.execution_backend == "local"
    assert settings.redis_url is None
    assert settings.worker_role == "cpu"
    assert settings.spatial_worker_backend == "fake"
    assert settings.spatial_weights_sha256 is None
    assert settings.ingest_concurrency == 2
    assert settings.cpu_decode_concurrency == 2
    assert settings.cpu_analysis_concurrency == 2
    assert settings.gpu_spatial_concurrency == 1
    assert settings.critic_concurrency == 1
    assert settings.critic_backend == "none"
    assert settings.critic_base_url is None
    assert settings.critic_model is None
    assert settings.critic_timeout_ms == 8_000
    assert settings.critic_api_key is None
    assert settings.native_thread_cap == 1
    assert settings.stage_retry_max_attempts == 3
    assert settings.stage_retry_base_ms == 1_000
    assert settings.stage_retry_cap_ms == 30_000
    assert settings.max_inflight_analyses == 32
    assert settings.min_free_bytes == 67_108_864
    assert settings.cleanup_max_age_ms == 86_400_000


@pytest.mark.parametrize(
    ("variable", "value", "attribute", "expected"),
    [
        ("CINE_ENVIRONMENT", "production", "environment", "production"),
        ("CINE_SERVICE_NAME", "cine-worker-cpu", "service_name", "cine-worker-cpu"),
        ("CINE_LOG_LEVEL", "WARNING", "log_level", "WARNING"),
        ("CINE_LOG_FORMAT", "console", "log_format", "console"),
        ("CINE_FFMPEG_BINARY", "/opt/bin/ffmpeg", "ffmpeg_binary", "/opt/bin/ffmpeg"),
        ("CINE_FFPROBE_BINARY", "/opt/bin/ffprobe", "ffprobe_binary", "/opt/bin/ffprobe"),
        ("CINE_FFPROBE_TIMEOUT_MS", "15000", "ffprobe_timeout_ms", 15000),
        ("CINE_FFMPEG_TIMEOUT_MS", "12000", "ffmpeg_timeout_ms", 12000),
        ("CINE_FFMPEG_MAX_STDOUT_BYTES", "4096", "ffmpeg_max_stdout_bytes", 4096),
        ("CINE_INGEST_CHUNK_BYTES", "8192", "ingest_chunk_bytes", 8192),
        ("CINE_ARTIFACT_ROOT", "/opt/cine/artifacts", "artifact_root", Path("/opt/cine/artifacts")),
        ("CINE_STATE_PATH", "/opt/cine/state.sqlite", "state_path", Path("/opt/cine/state.sqlite")),
        (
            "CINE_DATABASE_URL",
            "postgresql+pg8000://cine:@127.0.0.1:5432/cine",
            "database_url",
            "postgresql+pg8000://cine:@127.0.0.1:5432/cine",
        ),
        ("CINE_LEASE_TTL_MS", "5000", "lease_ttl_ms", 5000),
        ("CINE_WORKER_POLL_MS", "250", "worker_poll_ms", 250),
        ("CINE_WORKER_ID", "worker-7", "worker_id", "worker-7"),
        ("CINE_API_HOST", "192.0.2.10", "api_host", "192.0.2.10"),
        ("CINE_API_PORT", "9000", "api_port", 9000),
        (
            "CINE_API_PUBLIC_URL",
            "http://192.0.2.10:9000",
            "api_public_url",
            "http://192.0.2.10:9000",
        ),
        (
            "CINE_REDIS_URL",
            "redis://127.0.0.1:6379/0",
            "redis_url",
            "redis://127.0.0.1:6379/0",
        ),
        ("CINE_WORKER_ROLE", "gpu", "worker_role", "gpu"),
        ("CINE_SPATIAL_WORKER_BACKEND", "none", "spatial_worker_backend", "none"),
        (
            "CINE_SPATIAL_WEIGHTS_SHA256",
            "a" * 64,
            "spatial_weights_sha256",
            "a" * 64,
        ),
        ("CINE_INGEST_CONCURRENCY", "4", "ingest_concurrency", 4),
        ("CINE_CPU_DECODE_CONCURRENCY", "3", "cpu_decode_concurrency", 3),
        ("CINE_CPU_ANALYSIS_CONCURRENCY", "5", "cpu_analysis_concurrency", 5),
        ("CINE_GPU_SPATIAL_CONCURRENCY", "1", "gpu_spatial_concurrency", 1),
        ("CINE_CRITIC_CONCURRENCY", "2", "critic_concurrency", 2),
        ("CINE_CRITIC_BACKEND", "FAKE", "critic_backend", "fake"),
        (
            "CINE_CRITIC_BASE_URL",
            "http://127.0.0.1:11434",
            "critic_base_url",
            "http://127.0.0.1:11434",
        ),
        ("CINE_CRITIC_MODEL", "local-model", "critic_model", "local-model"),
        ("CINE_CRITIC_TIMEOUT_MS", "2500", "critic_timeout_ms", 2500),
        ("CINE_CRITIC_API_KEY", "secret", "critic_api_key", "secret"),
        ("CINE_NATIVE_THREAD_CAP", "8", "native_thread_cap", 8),
        ("CINE_STAGE_RETRY_MAX_ATTEMPTS", "6", "stage_retry_max_attempts", 6),
        ("CINE_STAGE_RETRY_BASE_MS", "250", "stage_retry_base_ms", 250),
        ("CINE_STAGE_RETRY_CAP_MS", "4000", "stage_retry_cap_ms", 4000),
        ("CINE_MAX_INFLIGHT_ANALYSES", "8", "max_inflight_analyses", 8),
        ("CINE_MIN_FREE_BYTES", "1024", "min_free_bytes", 1024),
        ("CINE_CLEANUP_MAX_AGE_MS", "1000", "cleanup_max_age_ms", 1000),
    ],
)
def test_environment_overrides_each_field(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
    attribute: str,
    expected: object,
) -> None:
    monkeypatch.setenv(variable, value)

    assert getattr(load_settings(), attribute) == expected


@pytest.mark.parametrize("written", ["debug", "Debug", "dEbUg", "DEBUG"])
def test_log_level_is_normalised_to_its_canonical_casing(
    monkeypatch: pytest.MonkeyPatch,
    written: str,
) -> None:
    """Operators type levels in whatever case they remember; the field has one form."""
    monkeypatch.setenv("CINE_LOG_LEVEL", written)

    assert load_settings().log_level == "DEBUG"


@pytest.mark.parametrize("written", ["CI", "Ci", "ci"])
def test_environment_is_normalised_to_lowercase(
    monkeypatch: pytest.MonkeyPatch,
    written: str,
) -> None:
    monkeypatch.setenv("CINE_ENVIRONMENT", written)

    assert load_settings().environment == "ci"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("CINE_LOG_LEVEL", "chatty"),
        ("CINE_LOG_FORMAT", "xml"),
        ("CINE_ENVIRONMENT", "staging"),
        ("CINE_SERVICE_NAME", ""),
        ("CINE_FFMPEG_BINARY", ""),
        ("CINE_FFPROBE_BINARY", ""),
        ("CINE_FFPROBE_TIMEOUT_MS", "0"),
        ("CINE_FFMPEG_TIMEOUT_MS", "0"),
        ("CINE_FFMPEG_MAX_STDOUT_BYTES", "1"),
        ("CINE_INGEST_CHUNK_BYTES", "1"),
        ("CINE_LEASE_TTL_MS", "0"),
        ("CINE_WORKER_POLL_MS", "0"),
        ("CINE_WORKER_ID", ""),
        ("CINE_API_PORT", "0"),
        ("CINE_API_PUBLIC_URL", ""),
        ("CINE_EXECUTION_BACKEND", "ray"),
        ("CINE_WORKER_ROLE", "tpu"),
        ("CINE_SPATIAL_WORKER_BACKEND", "sam"),
        ("CINE_CRITIC_BACKEND", "vllm"),
        ("CINE_CRITIC_TIMEOUT_MS", "0"),
        ("CINE_INGEST_CONCURRENCY", "0"),
        ("CINE_NATIVE_THREAD_CAP", "0"),
        ("CINE_STAGE_RETRY_MAX_ATTEMPTS", "0"),
        ("CINE_STAGE_RETRY_BASE_MS", "0"),
        ("CINE_STAGE_RETRY_CAP_MS", "0"),
        ("CINE_MAX_INFLIGHT_ANALYSES", "0"),
        ("CINE_MIN_FREE_BYTES", "-1"),
    ],
)
def test_an_invalid_value_is_rejected_and_names_its_field(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError) as caught:
        load_settings()

    field = variable.removeprefix("CINE_").lower()
    assert field in str(caught.value).lower()


def test_a_misspelled_variable_is_an_error_rather_than_a_silent_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure mode this guards against is a typo that appears to work."""
    monkeypatch.setenv("CINE_LOG_LEVL", "DEBUG")

    with pytest.raises(ValidationError, match="unknown environment variable") as caught:
        load_settings()

    assert "CINE_LOG_LEVL" in str(caught.value)


def test_the_rejection_message_lists_the_names_that_would_have_worked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CINE_LOG_LEVL", "DEBUG")

    with pytest.raises(ValidationError) as caught:
        load_settings()

    assert "CINE_LOG_LEVEL" in str(caught.value)


def test_a_variable_belonging_to_another_project_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only this project's prefix is policed; ``CINEMA_*`` is somebody else's namespace."""
    monkeypatch.setenv("CINEMA_LOG_LEVEL", "DEBUG")

    assert load_settings().log_level == "INFO"


def test_settings_are_immutable_after_validation() -> None:
    settings = load_settings()

    with pytest.raises(ValidationError, match="frozen"):
        settings.log_level = "DEBUG"  # type: ignore[misc]


def test_settings_are_hashable_so_they_can_key_a_cache() -> None:
    assert hash(load_settings()) == hash(Settings())


def test_celery_backend_requires_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "celery")

    with pytest.raises(ValidationError, match="redis_url"):
        load_settings()


def test_celery_backend_accepts_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_EXECUTION_BACKEND", "CELERY")
    monkeypatch.setenv("CINE_REDIS_URL", "redis://127.0.0.1:6379/0")

    settings = load_settings()

    assert settings.execution_backend == "celery"
    assert settings.redis_url == "redis://127.0.0.1:6379/0"


def test_empty_redis_url_and_weights_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_REDIS_URL", "   ")
    with pytest.raises(ValidationError, match="redis_url"):
        load_settings()

    monkeypatch.delenv("CINE_REDIS_URL", raising=False)
    monkeypatch.setenv("CINE_SPATIAL_WEIGHTS_SHA256", "")
    with pytest.raises(ValidationError, match="spatial_weights_sha256"):
        load_settings()


def test_openai_critic_requires_a_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_CRITIC_BACKEND", "openai")
    with pytest.raises(ValidationError, match="critic_base_url"):
        load_settings()

    monkeypatch.setenv("CINE_CRITIC_BASE_URL", "http://127.0.0.1:11434/v1")
    settings = load_settings()
    assert settings.critic_backend == "openai"
    assert settings.critic_base_url == "http://127.0.0.1:11434/v1"


def test_empty_critic_fields_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CINE_CRITIC_BASE_URL", "   ")
    with pytest.raises(ValidationError, match="critic_base_url"):
        load_settings()
    monkeypatch.delenv("CINE_CRITIC_BASE_URL", raising=False)
    monkeypatch.setenv("CINE_CRITIC_MODEL", "")
    with pytest.raises(ValidationError, match="critic_model"):
        load_settings()
    monkeypatch.delenv("CINE_CRITIC_MODEL", raising=False)
    monkeypatch.setenv("CINE_CRITIC_API_KEY", "")
    with pytest.raises(ValidationError, match="critic_api_key"):
        load_settings()
