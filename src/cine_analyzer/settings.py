"""The one boundary at which environment variables enter this process.

No other module reads ``os.environ``. Metric, adapter, and stage code receives a
validated :class:`Settings` instance instead of reaching for the environment, so
a configuration mistake surfaces once, at startup, with a field name attached.

These are deployment settings: where the process runs and how it talks. They are
deliberately *not* the analysis configuration, which is a separate, hashed
document owned by later phases (``docs/architecture/system-design.md`` section
14). Secrets and endpoints belong here and never in the hashed analysis config.
"""

import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "ENV_PREFIX",
    "Environment",
    "LogFormat",
    "LogLevel",
    "Settings",
    "load_settings",
]

ENV_PREFIX = "CINE_"


def _upper(value: object) -> object:
    return value.upper() if isinstance(value, str) else value


def _lower(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


Environment = Annotated[Literal["local", "ci", "production"], BeforeValidator(_lower)]
ExecutionBackend = Annotated[Literal["local", "celery"], BeforeValidator(_lower)]
WorkerRole = Annotated[Literal["cpu", "gpu"], BeforeValidator(_lower)]
SpatialWorkerBackend = Annotated[Literal["none", "fake", "ultralytics"], BeforeValidator(_lower)]
CriticBackend = Annotated[Literal["none", "fake", "openai"], BeforeValidator(_lower)]
LogFormat = Annotated[Literal["json", "console"], BeforeValidator(_lower)]
LogLevel = Annotated[
    Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    BeforeValidator(_upper),
]


class Settings(BaseSettings):
    """Immutable, validated deployment settings.

    Frozen, so a value cannot drift after the process has hashed or logged it.

    A misspelled ``CINE_*`` variable is an error rather than a silently ignored
    no-op, which is the failure mode that makes people distrust configuration.
    ``extra="forbid"`` alone does not achieve that: the environment source only
    looks up variables it already has a field for, so an unrecognised name never
    reaches the model. :meth:`_reject_unknown_environment_variables` closes it.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        extra="forbid",
        frozen=True,
        validate_default=True,
        case_sensitive=False,
        use_attribute_docstrings=True,
    )

    environment: Environment = "local"
    """Deployment profile name, used as a log field and to key operator defaults."""

    service_name: Annotated[str, Field(min_length=1, max_length=64)] = "cine-analyzer"
    """Value of the ``service`` field on every structured log event."""

    log_level: LogLevel = "INFO"
    log_format: LogFormat = "json"

    ffmpeg_binary: Annotated[str, Field(min_length=1)] = "ffmpeg"
    """Name or absolute path of the FFmpeg executable. Resolved, never shell-interpolated."""

    ffprobe_binary: Annotated[str, Field(min_length=1)] = "ffprobe"
    """Name or absolute path of the ffprobe executable. Resolved, never shell-interpolated."""

    ffprobe_timeout_ms: Annotated[int, Field(gt=0, le=300_000)] = 30_000
    """Wall time allowed for one ffprobe invocation, integer milliseconds."""

    ffmpeg_timeout_ms: Annotated[int, Field(gt=0, le=300_000)] = 30_000
    """Wall time allowed for one FFmpeg audio extract, integer milliseconds."""

    ffmpeg_max_stdout_bytes: Annotated[int, Field(ge=1024, le=500_000_000)] = 50_000_000
    """Stdout byte cap for one FFmpeg audio extract."""

    ingest_chunk_bytes: Annotated[int, Field(ge=4096, le=8_388_608)] = 65_536
    """Read/write chunk size while hashing an upload."""

    artifact_root: Path = Path("var/artifacts")
    """Filesystem root for quarantine, temporary, and canonical blobs."""

    state_path: Path = Path("var/state.sqlite")
    """Local SQLite file for the disposable Profile A repository. Not production state."""

    database_url: str | None = None
    """SQLAlchemy URL for PostgreSQL (``postgresql+pg8000://``). Required for API and worker."""

    lease_ttl_ms: Annotated[int, Field(gt=0, le=3_600_000)] = 120_000
    """Stage-lease time to live, integer milliseconds."""

    worker_poll_ms: Annotated[int, Field(gt=0, le=60_000)] = 500
    """Idle poll interval for the local worker, integer milliseconds."""

    worker_id: Annotated[str, Field(min_length=1, max_length=128)] = "local-worker"
    """Identity written onto acquired stage leases."""

    api_host: Annotated[str, Field(min_length=1, max_length=253)] = "127.0.0.1"
    """Bind address for ``cine-analyzer serve``."""

    api_port: Annotated[int, Field(ge=1, le=65535)] = 8000
    """Bind port for ``cine-analyzer serve``."""

    api_public_url: Annotated[str, Field(min_length=8, max_length=2048)] = "http://127.0.0.1:8000"
    """Base URL the dashboard HTTP client uses. No trailing slash required."""

    execution_backend: ExecutionBackend = "local"
    """``local`` polls PostgreSQL. ``celery`` submits StageCommand JSON to Redis."""

    redis_url: str | None = None
    """Redis broker URL (``redis://``). Required when ``execution_backend`` is celery."""

    worker_role: WorkerRole = "cpu"
    """Celery worker resource class. GPU workers consume only ``gpu_spatial``."""

    spatial_worker_backend: SpatialWorkerBackend = "fake"
    """Detector the GPU worker process initializes once. ``ultralytics`` fails readiness."""

    spatial_weights_sha256: str | None = None
    """Expected detector weights digest. When set, a mismatch fails GPU readiness."""

    ingest_concurrency: Annotated[int, Field(ge=1, le=32)] = 2
    cpu_decode_concurrency: Annotated[int, Field(ge=1, le=32)] = 2
    cpu_analysis_concurrency: Annotated[int, Field(ge=1, le=32)] = 2
    gpu_spatial_concurrency: Annotated[int, Field(ge=1, le=4)] = 1
    critic_concurrency: Annotated[int, Field(ge=1, le=8)] = 1
    critic_backend: CriticBackend = "none"
    """Interpretation adapter. ``none`` omits prose; ``fake`` is deterministic CI."""

    critic_base_url: str | None = None
    """OpenAI-compatible base URL. Required when ``critic_backend`` is openai."""

    critic_model: str | None = None
    """Model name sent to an OpenAI-compatible server."""

    critic_timeout_ms: Annotated[int, Field(gt=0, le=120_000)] = 8_000
    """Wall time allowed for one critic HTTP call, integer milliseconds."""

    critic_api_key: str | None = None
    """Optional bearer token. Never hashed; redacted in logs."""

    native_thread_cap: Annotated[int, Field(ge=1, le=64)] = 1
    """Cap for OpenMP/BLAS/OpenCV threads inside a worker process."""

    stage_retry_max_attempts: Annotated[int, Field(ge=1, le=32)] = 3
    stage_retry_base_ms: Annotated[int, Field(gt=0, le=3_600_000)] = 1_000
    stage_retry_cap_ms: Annotated[int, Field(gt=0, le=3_600_000)] = 30_000

    max_inflight_analyses: Annotated[int, Field(ge=1, le=10_000)] = 32
    """Cap on analyses in QUEUED, RUNNING, or CANCEL_REQUESTED. API backpressure."""

    min_free_bytes: Annotated[int, Field(ge=0, le=1_099_511_627_776)] = 67_108_864
    """Disk headroom required before ingest. Zero disables the check."""

    cleanup_max_age_ms: Annotated[int, Field(ge=0, le=31_536_000_000)] = 86_400_000
    """Age after which ``tmp`` and ``quarantine`` files may be deleted."""

    @model_validator(mode="after")
    def _celery_requires_a_redis_url(self) -> Self:
        if self.execution_backend == "celery" and self.redis_url is None:
            message = "redis_url is required when execution_backend is celery"
            raise ValueError(message)
        if self.redis_url is not None and self.redis_url.strip() == "":
            message = "redis_url must not be empty"
            raise ValueError(message)
        if self.spatial_weights_sha256 is not None and self.spatial_weights_sha256.strip() == "":
            message = "spatial_weights_sha256 must not be empty"
            raise ValueError(message)
        if self.critic_backend == "openai" and (
            self.critic_base_url is None or self.critic_base_url.strip() == ""
        ):
            message = "critic_base_url is required when critic_backend is openai"
            raise ValueError(message)
        if self.critic_base_url is not None and self.critic_base_url.strip() == "":
            message = "critic_base_url must not be empty"
            raise ValueError(message)
        if self.critic_model is not None and self.critic_model.strip() == "":
            message = "critic_model must not be empty"
            raise ValueError(message)
        if self.critic_api_key is not None and self.critic_api_key.strip() == "":
            message = "critic_api_key must not be empty"
            raise ValueError(message)
        return self

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_environment_variables(cls, data: object) -> object:
        """Refuse to start when the environment holds a ``CINE_*`` name no field claims."""
        known = {f"{ENV_PREFIX}{name.upper()}" for name in cls.model_fields}
        unknown = sorted(
            name
            for name in os.environ
            if name.upper().startswith(ENV_PREFIX) and name.upper() not in known
        )
        if unknown:
            message = (
                f"unknown environment variable(s): {', '.join(unknown)}. "
                f"Recognised names are: {', '.join(sorted(known))}."
            )
            raise ValueError(message)
        return data


def load_settings() -> Settings:
    """Read and validate ``CINE_*`` environment variables.

    Raises:
        pydantic.ValidationError: if a variable is unknown or holds a value the
            declared type rejects.
    """
    return Settings()
