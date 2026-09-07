"""Provenance completion order and evidence timestamps."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from tests.factories import SAMPLE_ID, make_artifact, make_provenance

from cine_analyzer.domain.artifacts import EvidenceFrame
from cine_analyzer.domain.types import SCHEMA_VERSION


def test_completion_cannot_precede_start() -> None:
    started = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="completed_at"):
        make_provenance(started_at=started, completed_at=started - timedelta(seconds=1))


def test_naive_datetimes_are_rejected() -> None:
    naive_start = datetime(2026, 9, 6, 12, 0)  # noqa: DTZ001
    naive_end = datetime(2026, 9, 6, 12, 1)  # noqa: DTZ001
    with pytest.raises(ValidationError):
        make_provenance(started_at=naive_start, completed_at=naive_end)


def test_evidence_keeps_requested_and_decoded_timestamps() -> None:
    frame = EvidenceFrame(
        sample_id=SAMPLE_ID,
        requested_ms=1000,
        decoded_ms=1004,
        frame_index=24,
        image=make_artifact(kind="frame", media_type="image/jpeg"),
        purposes=("CHROMATIC", "EVIDENCE"),
    )

    assert frame.requested_ms == 1000
    assert frame.decoded_ms == 1004
    assert frame.image.schema_version == SCHEMA_VERSION
