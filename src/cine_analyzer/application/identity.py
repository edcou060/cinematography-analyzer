"""Analysis identity. Matches system-design §4: media hash + canonical config + pipeline version."""

import hashlib
from uuid import UUID, uuid5

from cine_analyzer.domain.config import AnalysisConfig, canonical_json_bytes

__all__ = ["IDENTITY_NAMESPACE", "make_analysis_key", "stable_uuid"]

IDENTITY_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def make_analysis_key(*, video_sha256: str, config: AnalysisConfig) -> str:
    """SHA-256 of ``video_sha256 + canonical_config_json + pipeline_version``."""
    payload = (
        video_sha256.encode("ascii")
        + canonical_json_bytes(config)
        + config.pipeline_version.encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()


def stable_uuid(*parts: str) -> UUID:
    """Deterministic UUID for shot and sample identities."""
    return uuid5(IDENTITY_NAMESPACE, "\0".join(parts))
