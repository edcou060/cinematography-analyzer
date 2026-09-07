"""Analysis identity is the documented concatenation, not the config hash alone."""

from hashlib import sha256

from cine_analyzer.application.identity import make_analysis_key, stable_uuid
from cine_analyzer.domain.config import AnalysisConfig, canonical_json_bytes


def test_the_key_matches_the_documented_byte_concatenation() -> None:
    config = AnalysisConfig()
    video_sha = "a" * 64
    expected = sha256(
        video_sha.encode("ascii")
        + canonical_json_bytes(config)
        + config.pipeline_version.encode("utf-8")
    ).hexdigest()

    assert make_analysis_key(video_sha256=video_sha, config=config) == expected


def test_pipeline_version_changes_the_identity() -> None:
    base = AnalysisConfig()
    other = AnalysisConfig(pipeline_version="0.2.0")
    digest = "b" * 64

    assert make_analysis_key(video_sha256=digest, config=base) != make_analysis_key(
        video_sha256=digest,
        config=other,
    )


def test_stable_uuid_is_deterministic_and_sensitive_to_parts() -> None:
    assert stable_uuid("shot", "0") == stable_uuid("shot", "0")
    assert stable_uuid("shot", "0") != stable_uuid("shot", "1")
