"""Probed media, sampling plans, and audio-presence consistency."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.factories import (
    ANALYSIS_ID,
    SAMPLE_ID,
    SHOT_ID,
    VIDEO_ID,
    make_artifact,
    make_sampling_plan,
    make_video,
)

from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleRequest,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
)
from cine_analyzer.domain.time import Rational


def test_rotation_must_be_a_right_angle() -> None:
    with pytest.raises(ValidationError, match="display_rotation_degrees"):
        make_video(display_rotation_degrees=45)


def test_audio_codec_is_required_when_audio_is_present() -> None:
    with pytest.raises(ValidationError, match="audio_codec is required"):
        make_video(has_audio=True, audio_codec=None)
    with pytest.raises(ValidationError, match="audio_codec is required"):
        make_video(has_audio=True, audio_codec="")


def test_audio_codec_is_forbidden_when_audio_is_absent() -> None:
    with pytest.raises(ValidationError, match="audio_codec must be absent"):
        make_video(has_audio=False, audio_codec="aac")


def test_a_zero_duration_clip_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_video(duration_ms=0)


def test_uppercase_sha256_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_video(content_sha256="A" * 64)


def test_duplicate_sample_ids_are_rejected() -> None:
    request = SampleRequest(
        sample_id=SAMPLE_ID,
        shot_id=SHOT_ID,
        requested_ms=100,
        purposes=(SamplePurpose.MOTION,),
    )
    with pytest.raises(ValidationError, match="unique"):
        make_sampling_plan(requests=(request, request))


def test_an_unsupported_sampling_schema_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported"):
        SamplingPlan(
            schema_version="9.0",
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            method_version="1.0.0",
            requests=(),
        )


def test_a_sample_requires_at_least_one_purpose() -> None:
    with pytest.raises(ValidationError):
        SampleRequest(
            sample_id=uuid4(),
            shot_id=uuid4(),
            requested_ms=0,
            purposes=(),
        )


def test_frame_rate_denominator_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Rational(numerator=30000, denominator=0)


def test_a_decoded_sample_requires_pixels_and_a_timestamp() -> None:
    with pytest.raises(ValidationError, match="decoded_ms"):
        SampleResult(
            sample_id=SAMPLE_ID,
            shot_id=SHOT_ID,
            requested_ms=100,
            purposes=(SamplePurpose.EVIDENCE,),
            status=SampleStatus.DECODED,
        )
    with pytest.raises(ValidationError, match="unavailable reason"):
        SampleResult(
            sample_id=SAMPLE_ID,
            shot_id=SHOT_ID,
            requested_ms=100,
            decoded_ms=100,
            purposes=(SamplePurpose.EVIDENCE,),
            status=SampleStatus.DECODED,
            image=make_artifact(),
            unavailable_reason="nope",
        )


def test_an_unavailable_sample_cannot_carry_pixels() -> None:
    with pytest.raises(ValidationError, match="cannot carry"):
        SampleResult(
            sample_id=SAMPLE_ID,
            shot_id=SHOT_ID,
            requested_ms=100,
            decoded_ms=100,
            purposes=(SamplePurpose.EVIDENCE,),
            status=SampleStatus.UNAVAILABLE,
            unavailable_reason="missing",
        )
    with pytest.raises(ValidationError, match="requires a reason"):
        SampleResult(
            sample_id=SAMPLE_ID,
            shot_id=SHOT_ID,
            requested_ms=100,
            purposes=(SamplePurpose.EVIDENCE,),
            status=SampleStatus.UNAVAILABLE,
        )


def test_manifest_results_must_follow_the_plan() -> None:
    plan = make_sampling_plan()
    decoded = SampleResult(
        sample_id=SAMPLE_ID,
        shot_id=SHOT_ID,
        requested_ms=2000,
        decoded_ms=2000,
        frame_index=10,
        purposes=(SamplePurpose.CHROMATIC, SamplePurpose.EVIDENCE),
        status=SampleStatus.DECODED,
        image=make_artifact(),
    )
    SamplingManifest(
        schema_version="1.0",
        analysis_id=ANALYSIS_ID,
        video_id=VIDEO_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(decoded,),
    )
    with pytest.raises(ValidationError, match="follow the plan"):
        SamplingManifest(
            schema_version="1.0",
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            method_version="sampling-v1",
            plan=plan,
            results=(),
        )
    with pytest.raises(ValidationError, match="identity"):
        SamplingManifest(
            schema_version="1.0",
            analysis_id=uuid4(),
            video_id=VIDEO_ID,
            method_version="sampling-v1",
            plan=plan,
            results=(decoded,),
        )
    with pytest.raises(ValidationError, match="unsupported"):
        SamplingManifest(
            schema_version="9.0",
            analysis_id=ANALYSIS_ID,
            video_id=VIDEO_ID,
            method_version="sampling-v1",
            plan=plan,
            results=(decoded,),
        )
