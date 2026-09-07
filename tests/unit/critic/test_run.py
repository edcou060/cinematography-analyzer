"""run_critique caches, retries once, and never rewrites the report."""

from pathlib import Path
from uuid import uuid4

from tests.factories import (
    ANALYSIS_ID,
    DIGEST,
    make_artifact,
    make_availability,
    make_report,
    make_video,
)
from tests.unit.aggregation.memory_jobs import MemoryJobRepository
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.adapters.critic.fake import FakeCritic
from cine_analyzer.adapters.critic.noop import NoOpCritic
from cine_analyzer.application.critic import (
    build_critic,
    critique_cache_key,
    persist_critique_for_job,
    report_document_sha256,
    run_critique,
)
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.config import AnalysisConfig, CriticConfig
from cine_analyzer.domain.critic import CRITIC_PROMPT_VERSION, CriticInput
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.control import ReportSummaryRecord
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings


class _Scripted:
    def __init__(self, replies: list[str | AdapterError], identity: str = "scripted:v1") -> None:
        self.replies = replies
        self.calls = 0
        self._identity = identity

    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str, payload: CriticInput, *, timeout_ms: int) -> str:
        del prompt, payload, timeout_ms
        item = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(item, AdapterError):
            raise item
        return item


_GOOD = '{"sentences": ["The clip has 1 detected shots with mean length 4.0 s and median 4.0 s."]}'
_BAD_NUMBER = '{"sentences": ["The clip has 99 detected shots."]}'


def test_fake_run_is_ok_and_does_not_change_report_bytes() -> None:
    report = make_report()
    before = report.model_dump_json()
    cache: dict[str, object] = {}
    first = run_critique(report, adapter=FakeCritic(), timeout_ms=8000, cache=cache)
    second = run_critique(report, adapter=FakeCritic(), timeout_ms=8000, cache=cache)
    assert first.status is MetricStatus.OK
    assert first.text is not None
    assert "director" not in first.text.lower()
    assert first.prompt_version == CRITIC_PROMPT_VERSION
    assert first.input_report_sha256 == report_document_sha256(report)
    assert second is first
    assert report.model_dump_json() == before
    assert report.critique is None


def test_noop_is_omitted_not_computed() -> None:
    critique = run_critique(make_report(), adapter=NoOpCritic(), timeout_ms=8000)
    assert critique.status is MetricStatus.NOT_COMPUTED
    assert critique.text is None


def test_timeout_bad_claims_and_fenced_json() -> None:
    timeout = AdapterError("MODEL_TIMEOUT", "timed out", retryable=True, stage="critic")
    timed = run_critique(make_report(), adapter=_Scripted([timeout, timeout]), timeout_ms=10)
    assert timed.status is MetricStatus.FAILED
    recovered = run_critique(
        make_report(), adapter=_Scripted([_BAD_NUMBER, _GOOD]), timeout_ms=8000
    )
    assert recovered.status is MetricStatus.OK
    rejected = run_critique(
        make_report(), adapter=_Scripted([_BAD_NUMBER, _BAD_NUMBER]), timeout_ms=8000
    )
    assert rejected.status is MetricStatus.FAILED
    fenced = run_critique(
        make_report(),
        adapter=_Scripted([f"```json\n{_GOOD}\n```"]),
        timeout_ms=8000,
    )
    assert fenced.status is MetricStatus.OK


def test_cache_key_includes_prompt_model_and_input() -> None:
    payload = CriticInput.from_report(make_report())
    first = critique_cache_key(payload, prompt_version="critic-prompt-v1", identity="fake:a")
    second = critique_cache_key(payload, prompt_version="critic-prompt-v2", identity="fake:a")
    third = critique_cache_key(payload, prompt_version="critic-prompt-v1", identity="fake:b")
    other = critique_cache_key(
        payload.model_copy(
            update={"editing": payload.editing.model_copy(update={"shot_count": 2})}
        ),
        prompt_version="critic-prompt-v1",
        identity="fake:a",
    )
    assert len({first, second, third, other}) == 4


def test_build_critic_backends() -> None:
    assert build_critic(Settings()).identity().startswith("none:")
    assert build_critic(Settings(critic_backend="fake")).identity().startswith("fake:")
    assert build_critic(Settings(), backend="openai").identity() == "openai-compat:unconfigured"
    assert build_critic(Settings(), backend="ray").identity() == "none:unknown-backend"
    configured = build_critic(
        Settings(critic_backend="openai", critic_base_url="http://127.0.0.1:9", critic_model="m")
    )
    assert "openai-compat:m" in configured.identity()
    configured.close()  # type: ignore[attr-defined]
    default_model = build_critic(
        Settings(critic_backend="openai", critic_base_url="http://127.0.0.1:9")
    )
    assert "openai-compatible" in default_model.identity()
    default_model.close()  # type: ignore[attr-defined]


def test_persist_skips_saves_and_swallows_errors(tmp_path: Path) -> None:
    jobs = MemoryJobRepository()
    store = MemoryStore(tmp_path)
    video = VideoRecord(
        metadata=make_video(),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )
    jobs.insert_video(video)
    analysis = jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=ANALYSIS_ID,
            video_id=video.metadata.video_id,
            configuration_hash=DIGEST,
            pipeline_version="0.1.0",
            analysis_key="a" * 64,
            state=AnalysisState.SUCCEEDED,
        )
    )
    assert persist_critique_for_job(jobs, store, analysis.analysis_id, Settings()).status is (
        MetricStatus.NOT_COMPUTED
    )
    jobs.record_config(analysis.analysis_id, AnalysisConfig(critic=CriticConfig(enabled=True)))
    assert (
        persist_critique_for_job(jobs, store, analysis.analysis_id, Settings()).status
        is MetricStatus.NOT_COMPUTED
    )
    assert (
        persist_critique_for_job(
            jobs, store, analysis.analysis_id, Settings(critic_backend="fake")
        ).status
        is MetricStatus.FAILED
    )
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=analysis.analysis_id,
            summary=make_report().summary,
            availability=make_availability(),
            report_artifact_id=uuid4(),
            timeline_artifact_id=None,
        )
    )
    assert (
        persist_critique_for_job(
            jobs, store, analysis.analysis_id, Settings(critic_backend="fake")
        ).status
        is MetricStatus.FAILED
    )
    report = make_report(analysis_id=analysis.analysis_id)
    key = f"analyses/{analysis.analysis_id.hex}/report.json"
    artifact = make_artifact(kind="analysis_report")
    jobs.insert_artifact(artifact, storage_key=key)
    jobs.save_report_summary(
        ReportSummaryRecord(
            analysis_id=analysis.analysis_id,
            summary=report.summary,
            availability=make_availability(),
            report_artifact_id=artifact.artifact_id,
            timeline_artifact_id=None,
        )
    )
    assert (
        persist_critique_for_job(
            jobs, store, analysis.analysis_id, Settings(critic_backend="fake")
        ).status
        is MetricStatus.FAILED
    )
    store.put_bytes(report.model_dump_json().encode("utf-8"), storage_key=key)
    saved = persist_critique_for_job(
        jobs, store, analysis.analysis_id, Settings(critic_backend="fake")
    )
    assert saved.status is MetricStatus.OK
    reused = persist_critique_for_job(
        jobs, store, analysis.analysis_id, Settings(critic_backend="fake")
    )
    assert reused.text == saved.text
    assert persist_critique_for_job(
        jobs, store, uuid4(), Settings(critic_backend="fake")
    ).status is (MetricStatus.NOT_COMPUTED)

    def _boom(_record: object) -> None:
        raise AdapterError("RESOURCE_STATE", "write failed", retryable=True, stage="control")

    jobs.save_critique = _boom  # type: ignore[method-assign]
    jobs._critiques.clear()
    assert (
        persist_critique_for_job(
            jobs, store, analysis.analysis_id, Settings(critic_backend="fake")
        ).status
        is MetricStatus.FAILED
    )
