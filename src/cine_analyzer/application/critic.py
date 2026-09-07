"""Run an optional critique. Failures omit prose and never rewrite metrics."""

import hashlib
import json
import math
import re
from collections.abc import MutableMapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from cine_analyzer.adapters.critic.fake import FakeCritic
from cine_analyzer.adapters.critic.noop import NoOpCritic
from cine_analyzer.adapters.critic.openai_compat import OpenAICompatCritic
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.config import canonical_json_bytes
from cine_analyzer.domain.critic import CRITIC_PROMPT_VERSION, CriticInput, CriticOutput
from cine_analyzer.domain.report import AnalysisReport, Critique
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.logging_setup import get_logger
from cine_analyzer.ports.control import CritiqueRunRecord, JobRepository
from cine_analyzer.ports.critic import Critic
from cine_analyzer.ports.ingestion import ArtifactStore
from cine_analyzer.settings import Settings

__all__ = [
    "CRITIC_SYSTEM_PROMPT",
    "audit_critique",
    "build_critic",
    "critique_cache_key",
    "persist_critique_for_job",
    "report_document_sha256",
    "run_critique",
]

CRITIC_SYSTEM_PROMPT = (
    "You are an optional cinematography-metrics interpreter. "
    "Use only the JSON fields supplied. Do not infer a director, genre, story, emotion, "
    "budget, camera, lens, or artistic quality. Lighting-key and framing labels are estimates. "
    "Thirds proximity is geometric, not composition quality. Tension proxy is not audience "
    "emotion. Shots are detected edit intervals, not narrative scenes. "
    'Reply with JSON: {"sentences": ["..."]} with at most three sentences and no extra keys. '
    "Each sentence at most 200 characters. Mention only numbers and hex colours that appear "
    "in the input."
)

_FORBIDDEN_PHRASES: tuple[str, ...] = (
    "director",
    "genre",
    "story",
    "narrative scene",
    "emotion",
    "budget",
    "camera",
    "lens",
    "masterpiece",
    "cinematic quality",
    "beautiful",
    "poorly",
    "spielberg",
    "nolan",
    "film noir",
    "audience",
    "expensive",
    "anamorphic",
    "original_filename",
    ".mp4",
    ".mov",
    "/users/",
    "\\\\",
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def build_critic(settings: Settings, *, backend: str | None = None) -> Critic:
    """Construct the configured adapter. CLI may override the backend name."""
    chosen = settings.critic_backend if backend is None else backend
    if chosen == "none":
        return NoOpCritic()
    if chosen == "fake":
        return FakeCritic()
    if chosen == "openai":
        url = settings.critic_base_url
        if url is None or url.strip() == "":
            return NoOpCritic(identity="openai-compat:unconfigured")
        model = settings.critic_model if settings.critic_model is not None else "openai-compatible"
        return OpenAICompatCritic(
            base_url=url,
            model=model,
            api_key=settings.critic_api_key,
        )
    return NoOpCritic(identity="none:unknown-backend")


def report_document_sha256(report: AnalysisReport) -> str:
    """SHA-256 of the report document with critique omitted."""
    stripped = report.model_copy(update={"critique": None})
    return hashlib.sha256(canonical_json_bytes(stripped)).hexdigest()


def critique_cache_key(payload: CriticInput, *, prompt_version: str, identity: str) -> str:
    """SHA-256 of canonical CriticInput JSON + prompt version + adapter identity."""
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes(payload))
    digest.update(prompt_version.encode("utf-8"))
    digest.update(identity.encode("utf-8"))
    return digest.hexdigest()


def run_critique(
    report: AnalysisReport,
    *,
    adapter: Critic,
    timeout_ms: int,
    cache: MutableMapping[str, Critique] | None = None,
    peak_ms: tuple[int, ...] = (),
) -> Critique:
    """Build CriticInput, complete, validate, audit (one retry), never raise for model errors."""
    payload = CriticInput.from_report(report, peak_ms=peak_ms)
    report_sha = report_document_sha256(report)
    identity = adapter.identity()
    cache_key = critique_cache_key(payload, prompt_version=CRITIC_PROMPT_VERSION, identity=identity)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    omitted = Critique(
        status=MetricStatus.NOT_COMPUTED,
        text=None,
        model_name=identity,
        prompt_version=CRITIC_PROMPT_VERSION,
        input_report_sha256=report_sha,
    )
    if identity.startswith("none:"):
        return _store(cache, cache_key, omitted)
    failed = Critique(
        status=MetricStatus.FAILED,
        text=None,
        model_name=identity,
        prompt_version=CRITIC_PROMPT_VERSION,
        input_report_sha256=report_sha,
    )
    parsed: CriticOutput | None = None
    for _attempt in range(2):
        try:
            raw = adapter.complete(CRITIC_SYSTEM_PROMPT, payload, timeout_ms=timeout_ms)
            parsed = _parse_output(raw)
        except (AdapterError, ValidationError, ValueError):
            parsed = None
            continue
        ok, _reason = audit_critique(parsed, payload)
        if ok:
            result = Critique(
                status=MetricStatus.OK,
                text=parsed.as_text(),
                model_name=identity,
                prompt_version=CRITIC_PROMPT_VERSION,
                input_report_sha256=report_sha,
            )
            return _store(cache, cache_key, result)
        parsed = None
    del parsed
    return _store(cache, cache_key, failed)


def persist_critique_for_job(
    jobs: JobRepository,
    store: ArtifactStore,
    analysis_id: UUID,
    settings: Settings,
) -> Critique:
    """Load the stored report, run the critic, save a row. Never fails the analysis."""
    omitted = Critique(status=MetricStatus.NOT_COMPUTED)
    failed = Critique(status=MetricStatus.FAILED)
    try:
        job = jobs.load_job(analysis_id)
        skip_reason: str | None = None
        if job is None or not job.config.critic.enabled:
            skip_reason = "critic_not_requested"
        elif settings.critic_backend == "none":
            skip_reason = "backend_none"
        if skip_reason is not None:
            get_logger(__name__).info("critic.skipped", reason=skip_reason)
            return omitted
        adapter = build_critic(settings)
        summary = jobs.get_report_summary(analysis_id)
        artifact = None if summary is None else jobs.get_artifact(summary.report_artifact_id)
        if summary is None or artifact is None:
            reason = "report_missing" if summary is None else "artifact_missing"
            get_logger(__name__).info("critic.failed", reason=reason)
            return failed
        payload = store.local_path(artifact.storage_key).read_bytes()
        report = AnalysisReport.model_validate_json(payload)
        report_sha = report_document_sha256(report)
        existing = jobs.get_critique_by_identity(
            analysis_id,
            prompt_version=CRITIC_PROMPT_VERSION,
            model_name=adapter.identity(),
            input_report_sha256=report_sha,
        )
        if existing is not None:
            return existing.critique
        critique = run_critique(
            report,
            adapter=adapter,
            timeout_ms=settings.critic_timeout_ms,
        )
        jobs.save_critique(
            CritiqueRunRecord(
                critique_run_id=uuid4(),
                analysis_id=analysis_id,
                critique=critique,
                created_at=datetime.now(tz=UTC),
            )
        )
    except (AdapterError, OSError, ValueError, ValidationError):
        get_logger(__name__).info("critic.failed", reason="persist_error")
        return failed
    return critique


def audit_critique(output: CriticOutput, payload: CriticInput) -> tuple[bool, str]:
    """Reject forbidden stems and numbers/colours that are not in CriticInput."""
    text = output.as_text()
    lowered = text.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:
            return False, f"forbidden phrase {phrase!r}"
    allowed_hex = {item.upper() for item in payload.palette}
    for match in _HEX.finditer(text):
        if match.group(0).upper() not in allowed_hex:
            return False, "hex colour is not in the critic input"
    stripped = _HEX.sub(" ", text)
    allowed_numbers = _allowed_numbers(payload)
    for match in _NUMBER.finditer(stripped):
        value = float(match.group(0))
        if not _number_allowed(value, allowed_numbers):
            return False, f"number {value} is not in the critic input"
    return True, "ok"


def _allowed_numbers(payload: CriticInput) -> tuple[float, ...]:
    values: list[float] = [
        float(payload.editing.shot_count),
        payload.editing.asl_seconds,
        payload.editing.median_seconds,
        payload.lighting.low_key_ratio,
        payload.lighting.valid_shot_ratio,
        payload.composition.valid_shot_ratio,
        float(len(payload.palette)),
    ]
    if payload.composition.median_thirds_proximity is not None:
        values.append(payload.composition.median_thirds_proximity)
    values.extend(payload.tension_proxy.peak_seconds)
    extras: list[float] = []
    for item in values:
        extras.append(round(item * 100.0))
        extras.append(round(item * 100.0, 1))
    values.extend(extras)
    return tuple(values)


def _number_allowed(value: float, allowed: tuple[float, ...]) -> bool:
    return any(math.isclose(value, candidate, rel_tol=0.0, abs_tol=0.011) for candidate in allowed)


def _parse_output(raw: str) -> CriticOutput:
    text = raw.strip()
    if text.startswith("```"):
        text = _FENCE.sub("", text).strip()
    document = json.loads(text)
    return CriticOutput.model_validate(document)


def _store(
    cache: MutableMapping[str, Critique] | None, cache_key: str, critique: Critique
) -> Critique:
    if cache is not None:
        cache[cache_key] = critique
    return critique
