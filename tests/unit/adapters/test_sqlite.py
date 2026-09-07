"""Disposable SQLite repository: unique hashes, unique analysis keys, rollback."""

import sqlite3
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from tests.factories import DIGEST, make_artifact, make_video

from cine_analyzer.adapters.persistence.sqlite import SqliteAnalysisRepository
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.jobs import AnalysisState
from cine_analyzer.ports.ingestion import AnalysisRecord, VideoRecord


def _video(content_sha256: str = DIGEST) -> VideoRecord:
    return VideoRecord(
        metadata=make_video(content_sha256=content_sha256, probe_artifact=make_artifact()),
        original_storage_key="aa/" + "a" * 64,
        probe_storage_key="bb/" + "b" * 64,
    )


def _analysis(
    video: VideoRecord, *, analysis_key: str, configuration_hash: str = DIGEST
) -> AnalysisRecord:
    return AnalysisRecord(
        analysis_id=uuid4(),
        video_id=video.metadata.video_id,
        configuration_hash=configuration_hash,
        pipeline_version="0.1.0",
        analysis_key=analysis_key,
        state=AnalysisState.QUEUED,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[SqliteAnalysisRepository]:
    instance = SqliteAnalysisRepository(tmp_path / "nested" / "state.sqlite")
    try:
        yield instance
    finally:
        instance.close()


def test_insert_and_get_video_round_trip(repo: SqliteAnalysisRepository) -> None:
    record = _video()
    stored = repo.insert_video(record)
    fetched = repo.get_video_by_hash(DIGEST)

    assert stored.metadata.video_id == record.metadata.video_id
    assert fetched is not None
    assert fetched.metadata == record.metadata
    assert repo.get_video_by_hash("c" * 64) is None


def test_duplicate_content_hash_returns_the_original(repo: SqliteAnalysisRepository) -> None:
    first = repo.insert_video(_video())
    second = _video()
    second = VideoRecord(
        metadata=make_video(video_id=uuid4(), content_sha256=DIGEST),
        original_storage_key="cc/" + "c" * 64,
        probe_storage_key="dd/" + "d" * 64,
    )
    reused = repo.insert_video(second)
    assert reused.metadata.video_id == first.metadata.video_id


def test_analysis_identity_is_unique_and_reusable(repo: SqliteAnalysisRepository) -> None:
    video = repo.insert_video(_video())
    key = sha256(b"analysis-one").hexdigest()
    first = repo.insert_analysis(_analysis(video, analysis_key=key))
    second = repo.insert_analysis(_analysis(video, analysis_key=key))
    assert second.analysis_id == first.analysis_id
    assert repo.get_analysis_by_key(key) == first
    assert repo.get_analysis_by_key("e" * 64) is None


def test_artifact_insert_is_idempotent_on_storage_key(repo: SqliteAnalysisRepository) -> None:
    ref = make_artifact()
    repo.insert_artifact(ref, storage_key="ee/" + "e" * 64)
    other = make_artifact(artifact_id=uuid4())
    repo.insert_artifact(other, storage_key="ee/" + "e" * 64)


def test_analysis_without_a_video_is_a_state_error(repo: SqliteAnalysisRepository) -> None:
    video = _video()
    with pytest.raises(AdapterError) as caught:
        repo.insert_analysis(_analysis(video, analysis_key=sha256(b"orphan").hexdigest()))
    assert caught.value.code == "RESOURCE_STATE"


def test_conflicting_primary_key_without_matching_hash_is_a_state_error(
    repo: SqliteAnalysisRepository,
) -> None:
    repo.insert_video(_video())
    other_hash = sha256(b"other-bytes").hexdigest()
    colliding = VideoRecord(
        metadata=make_video(content_sha256=other_hash),
        original_storage_key="ff/" + "f" * 64,
        probe_storage_key="gg/" + "g" * 64,
    )
    with pytest.raises(AdapterError) as caught:
        repo.insert_video(colliding)
    assert caught.value.code == "RESOURCE_STATE"


def test_conflicting_analysis_triple_without_matching_key_is_a_state_error(
    repo: SqliteAnalysisRepository,
) -> None:
    video = repo.insert_video(_video())
    repo.insert_analysis(_analysis(video, analysis_key=sha256(b"k1").hexdigest()))
    with pytest.raises(AdapterError) as caught:
        repo.insert_analysis(_analysis(video, analysis_key=sha256(b"k2").hexdigest()))
    assert caught.value.code == "RESOURCE_STATE"


def test_closed_connection_maps_to_resource_state(repo: SqliteAnalysisRepository) -> None:
    repo.close()
    with pytest.raises(AdapterError) as caught:
        repo.get_video_by_hash(DIGEST)
    assert caught.value.code == "RESOURCE_STATE"
    with pytest.raises(AdapterError):
        repo.get_analysis_by_key(DIGEST)
    with pytest.raises(AdapterError):
        repo.insert_video(_video(content_sha256=sha256(b"closed").hexdigest()))
    with pytest.raises(AdapterError):
        repo.insert_artifact(make_artifact(artifact_id=uuid4()), storage_key="hh/" + "h" * 64)
    with pytest.raises(AdapterError):
        repo.insert_analysis(_analysis(_video(), analysis_key=sha256(b"closed-a").hexdigest()))


def test_initialisation_failure_is_a_resource_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("cannot open")

    monkeypatch.setattr("cine_analyzer.adapters.persistence.sqlite.sqlite3.connect", boom)
    with pytest.raises(AdapterError) as caught:
        SqliteAnalysisRepository(tmp_path / "state.sqlite")
    assert caught.value.code == "RESOURCE_STATE"


def test_schema_failure_is_a_resource_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BoomConnection:
        row_factory = None

        def executescript(self, _sql: str) -> None:
            raise sqlite3.OperationalError("schema")

        def execute(self, *_args: object, **_kwargs: object) -> sqlite3.Cursor:
            raise sqlite3.OperationalError("schema")

    monkeypatch.setattr(
        "cine_analyzer.adapters.persistence.sqlite.sqlite3.connect",
        lambda *_args, **_kwargs: BoomConnection(),
    )
    with pytest.raises(AdapterError) as caught:
        SqliteAnalysisRepository(tmp_path / "state.sqlite")
    assert caught.value.code == "RESOURCE_STATE"
