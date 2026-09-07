"""In-flight quota allows reuse and blocks a new identity."""

from hashlib import sha256
from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_video
from tests.unit.aggregation.memory_jobs import MemoryJobRepository

from cine_analyzer.application.errors import IngestError
from cine_analyzer.application.identity import make_analysis_key
from cine_analyzer.application.quota import enforce_inflight_quota
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord
from cine_analyzer.settings import Settings


def _video(digest: str) -> VideoRecord:
    return VideoRecord(
        metadata=make_video(content_sha256=digest, video_id=uuid4()),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )


def test_quota_skips_existing_identity_and_blocks_a_new_one() -> None:
    jobs = MemoryJobRepository()
    config = AnalysisConfig()
    first = _video(DIGEST)
    jobs.insert_video(first)
    jobs.insert_analysis(
        AnalysisRecord(
            analysis_id=uuid4(),
            video_id=first.metadata.video_id,
            configuration_hash=config.hash(),
            pipeline_version=config.pipeline_version,
            analysis_key=make_analysis_key(
                video_sha256=first.metadata.content_sha256, config=config
            ),
            state=AnalysisState.QUEUED,
        )
    )
    settings = Settings(max_inflight_analyses=1)
    enforce_inflight_quota(jobs, settings, video=first, config=config, request_id="r")
    second = _video(sha256(b"other").hexdigest())
    with pytest.raises(IngestError) as caught:
        enforce_inflight_quota(jobs, settings, video=second, config=config, request_id="r")
    assert caught.value.safe.code == "RESOURCE_LIMIT"


def test_quota_allows_a_new_identity_under_the_cap() -> None:
    jobs = MemoryJobRepository()
    config = AnalysisConfig()
    video = _video(DIGEST)
    jobs.insert_video(video)
    enforce_inflight_quota(
        jobs, Settings(max_inflight_analyses=1), video=video, config=config, request_id="r"
    )
