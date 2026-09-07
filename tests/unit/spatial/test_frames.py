"""Load composition JPEGs for one shot."""

from pathlib import Path
from uuid import uuid4

from tests.factories import ANALYSIS_ID, SAMPLE_ID, SHOT_ID, make_artifact
from tests.unit.application.fakes import MemoryStore

from cine_analyzer.application.spatial import collect_spatial_frames
from cine_analyzer.domain.media import (
    SamplePurpose,
    SampleRequest,
    SampleResult,
    SampleStatus,
    SamplingManifest,
    SamplingPlan,
)
from cine_analyzer.domain.types import SCHEMA_VERSION


def test_collect_spatial_frames_keeps_composition_samples(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    jpeg = b"\xff\xd8fake"
    blob = store.put_bytes(jpeg, storage_key="aa/" + "a" * 64)
    evidence_id = uuid4()
    plan = SamplingPlan(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=SHOT_ID,
        method_version="sampling-v1",
        requests=(
            SampleRequest(
                sample_id=SAMPLE_ID,
                shot_id=SHOT_ID,
                requested_ms=100,
                purposes=(SamplePurpose.COMPOSITION,),
            ),
            SampleRequest(
                sample_id=evidence_id,
                shot_id=SHOT_ID,
                requested_ms=200,
                purposes=(SamplePurpose.EVIDENCE,),
            ),
        ),
    )
    manifest = SamplingManifest(
        schema_version=SCHEMA_VERSION,
        analysis_id=ANALYSIS_ID,
        video_id=SHOT_ID,
        method_version="sampling-v1",
        plan=plan,
        results=(
            SampleResult(
                sample_id=SAMPLE_ID,
                shot_id=SHOT_ID,
                requested_ms=100,
                decoded_ms=120,
                purposes=(SamplePurpose.COMPOSITION,),
                status=SampleStatus.DECODED,
                image=make_artifact(),
            ),
            SampleResult(
                sample_id=evidence_id,
                shot_id=SHOT_ID,
                requested_ms=200,
                decoded_ms=200,
                purposes=(SamplePurpose.EVIDENCE,),
                status=SampleStatus.DECODED,
                image=make_artifact(),
            ),
        ),
    )
    frames = collect_spatial_frames(manifest, {SAMPLE_ID: blob.storage_key}, store, SHOT_ID)
    assert len(frames) == 1
    assert frames[0].jpeg == jpeg
