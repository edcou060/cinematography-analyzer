"""Dark-but-not-letterbox frames still receive a low-key estimate."""

from uuid import uuid4

from tests.unit.chromatic.jpeg_util import encode_jpeg, solid_rgb

from cine_analyzer.adapters.vision.opencv_chromatics import OpenCvChromaticAnalyzer
from cine_analyzer.domain.chromatics import LightingKeyLabel
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.domain.types import MetricStatus
from cine_analyzer.ports.chromatics import ChromaticFrame


def test_dark_gray_is_a_low_key_estimate() -> None:
    frame = ChromaticFrame(sample_id=uuid4(), jpeg=encode_jpeg(solid_rgb((45, 45, 45), size=48)))
    result = OpenCvChromaticAnalyzer().analyze_shot((frame,), AnalysisConfig().chromatic)
    assert result.status is MetricStatus.OK
    assert result.value is not None
    assert result.value.lighting_key is LightingKeyLabel.LOW_KEY_ESTIMATE
    assert result.confidence is not None
    assert 0.0 < result.confidence <= 1.0
