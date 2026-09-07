"""CreateAnalysis reuses the analysis key and starts life QUEUED."""

import pytest
from tests.unit.application.fakes import (
    REQUEST_ID,
    FakeRepository,
    tiny_config,
    unique_analysis_record,
    video_record_from_bytes,
)

from cine_analyzer.application.analyze import CreateAnalysis
from cine_analyzer.application.errors import AdapterError, IngestError
from cine_analyzer.application.identity import make_analysis_key
from cine_analyzer.domain.jobs import AnalysisState


def test_a_new_analysis_is_queued() -> None:
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip")
    result = CreateAnalysis(repo).execute(video=video, config=tiny_config(), request_id=REQUEST_ID)

    assert result.reused is False
    assert result.analysis.state is AnalysisState.QUEUED
    assert result.analysis.video_id == video.metadata.video_id
    assert result.analysis.analysis_key == make_analysis_key(
        video_sha256=video.metadata.content_sha256,
        config=tiny_config(),
    )
    assert result.configuration_hash == tiny_config().hash()


def test_the_same_identity_is_reused() -> None:
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip")
    usecase = CreateAnalysis(repo)
    first = usecase.execute(video=video, config=tiny_config(), request_id=REQUEST_ID)
    second = usecase.execute(video=video, config=tiny_config(), request_id=REQUEST_ID)

    assert second.reused is True
    assert second.analysis.analysis_id == first.analysis.analysis_id


def test_an_insert_collision_is_reported_as_reuse() -> None:
    repo = FakeRepository()
    video = video_record_from_bytes(b"clip")
    other = unique_analysis_record(video)
    repo.replace_analysis_on_insert = other
    result = CreateAnalysis(repo).execute(video=video, config=tiny_config(), request_id=REQUEST_ID)

    assert result.reused is True
    assert result.analysis.analysis_id == other.analysis_id


def test_adapter_failures_use_the_analyze_stage() -> None:
    repo = FakeRepository()
    repo.insert_error = AdapterError(
        "RESOURCE_STATE", "local state could not be written", retryable=True
    )
    video = video_record_from_bytes(b"clip")

    with pytest.raises(IngestError) as caught:
        CreateAnalysis(repo).execute(video=video, config=tiny_config(), request_id=REQUEST_ID)

    assert caught.value.safe.code == "RESOURCE_STATE"
    assert caught.value.safe.stage == "analyze"
    assert caught.value.safe.request_id == REQUEST_ID
