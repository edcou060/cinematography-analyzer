"""SpatialShotAnalyzer: none/fake backends, no-subject, and wrapping."""

from uuid import uuid4

from tests.factories import make_provenance
from tests.unit.spatial.helpers import (
    box,
    fake_analyzer,
    gray_frame,
    hit,
    magenta_frame,
    spatial_config,
)

from cine_analyzer.adapters.vision.opencv_overlay import OpenCvOverlayRenderer
from cine_analyzer.application.spatial import (
    SpatialShotAnalyzer,
    _median,
    _percentile,
    wrap_spatial_measurement,
)
from cine_analyzer.application.spatial_select import CoverageAreaConfidenceSelector
from cine_analyzer.application.spatial_track import IoUSubjectTracker
from cine_analyzer.domain.spatial import FramingLabel, SpatialValue
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.spatial import SpatialComputeResult, SpatialFrame


def test_none_backend_is_detector_not_installed() -> None:
    result = fake_analyzer().analyze_shot((magenta_frame(),), spatial_config())
    assert result.status is MetricStatus.NOT_COMPUTED
    assert result.reason_code == "detector_not_installed"
    assert result.value is None
    assert result.overlays == ()


def test_unknown_backend_degrades_like_none() -> None:
    result = fake_analyzer().analyze_shot(
        (magenta_frame(),),
        spatial_config(backend="ultralytics"),
    )
    assert result.status is MetricStatus.NOT_COMPUTED
    assert result.reason_code == "detector_not_installed"


def test_fake_backend_without_a_detector_adapter_is_unavailable() -> None:
    analyzer = SpatialShotAnalyzer(
        {},
        IoUSubjectTracker(),
        CoverageAreaConfidenceSelector(),
        OpenCvOverlayRenderer(),
    )
    result = analyzer.analyze_shot((magenta_frame(),), spatial_config(backend="fake"))
    assert result.status is MetricStatus.NOT_COMPUTED
    assert result.reason_code == "detector_not_installed"


def test_fake_backend_without_frames_is_insufficient() -> None:
    result = fake_analyzer().analyze_shot((), spatial_config(backend="fake"))
    assert result.status is MetricStatus.INSUFFICIENT_DATA
    assert result.reason_code == "spatial_no_decoded_samples"
    assert result.value is None


def test_gray_frames_are_no_subject_not_zeros() -> None:
    frames = (gray_frame(), gray_frame(), gray_frame())
    result = fake_analyzer().analyze_shot(frames, spatial_config(backend="fake"))
    assert result.status is MetricStatus.NO_SUBJECT
    assert result.reason_code == "spatial_no_subject"
    assert result.value is None
    assert result.overlays  # guides are still drawn


def test_magenta_frames_yield_a_medium_estimate() -> None:
    frames = (magenta_frame(), magenta_frame())
    result = fake_analyzer().analyze_shot(frames, spatial_config(backend="fake"))
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert result.value.framing is FramingLabel.MEDIUM_ESTIMATE
    assert result.value.thirds_proximity_score > 0.4
    assert "quality" not in SpatialValue.model_fields
    assert result.overlays
    wrapped = wrap_spatial_measurement(result, method=make_provenance(method="spatial.fake"))
    assert wrapped.status is MetricStatus.OK
    assert wrapped.value is result.value


def test_scripted_unstable_track_is_no_subject() -> None:
    present = uuid4()
    missing_a = uuid4()
    missing_b = uuid4()
    scripted = hit(present, box(0.2, 0.2, 0.5, 0.8))
    analyzer = fake_analyzer({present: (scripted,), missing_a: (), missing_b: ()})
    frames = (gray_frame(present), gray_frame(missing_a), gray_frame(missing_b))
    result = analyzer.analyze_shot(frames, spatial_config(backend="fake"))
    assert result.status is MetricStatus.NO_SUBJECT
    assert result.reason_code == "spatial_no_subject"
    assert result.value is None


def test_scripted_hit_on_undecodable_jpeg_skips_overlay() -> None:
    sample = uuid4()
    scripted = hit(sample, box(0.2, 0.2, 0.5, 0.8))
    analyzer = fake_analyzer({sample: (scripted,)})
    frame = SpatialFrame(sample_id=sample, jpeg=b"not-a-jpeg")
    result = analyzer.analyze_shot((frame,), spatial_config(backend="fake"))
    assert result.status is MetricStatus.OK
    assert result.overlays == ()


def test_wrap_without_a_reason_uses_spatial_unavailable() -> None:
    wrapped = wrap_spatial_measurement(
        SpatialComputeResult(
            status=MetricStatus.FAILED,
            value=None,
            confidence=None,
            reason_code=None,
            evidence_sample_ids=(),
            observations=(),
            overlays=(),
        ),
        method=make_provenance(method="spatial.fake"),
    )
    assert wrapped.reason_code == "spatial_unavailable"


def test_percentile_and_median_helpers() -> None:
    assert _percentile([], 10.0) == 0.0
    assert _percentile([0.2, 0.4, 0.8], 10.0) == 0.2
    assert _median([1.0, 3.0]) == 2.0
    assert _median([1.0, 2.0, 3.0]) == 2.0
