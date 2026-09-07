"""Write an HTML swatch page for the chromatic golden frames."""

from __future__ import annotations

import html
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from cine_analyzer.adapters.vision.opencv_chromatics import OpenCvChromaticAnalyzer
from cine_analyzer.domain.config import AnalysisConfig
from cine_analyzer.ports.chromatics import ChromaticFrame

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "build" / "chromatic-goldens.html"


def _jpeg(rgb: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(
        ".jpg",
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        [int(cv2.IMWRITE_JPEG_QUALITY), 100],
    )
    if not ok:
        message = "jpeg encode failed"
        raise RuntimeError(message)
    return bytes(buffer.tobytes())


def _solid(color: tuple[int, int, int], size: int = 48) -> np.ndarray:
    frame = np.zeros((size, size, 3), dtype=np.uint8)
    frame[:, :] = color
    return frame


def golden_frames() -> dict[str, np.ndarray]:
    """Frames reviewed by tests/golden/chromatic/test_frames.py."""
    mixture = np.zeros((50, 50, 3), dtype=np.uint8)
    mixture[:, :] = (220, 30, 30)
    mixture[:, 40:] = (30, 30, 220)
    gradient_row = np.linspace(0, 255, 128, dtype=np.uint8)
    gradient = np.stack([np.tile(gradient_row, (48, 1))] * 3, axis=2)
    letterboxed = np.zeros((60, 80, 3), dtype=np.uint8)
    letterboxed[10:50, :, :] = (20, 180, 40)
    three = np.zeros((48, 144, 3), dtype=np.uint8)
    three[:, :48] = (200, 20, 20)
    three[:, 48:96] = (20, 200, 20)
    three[:, 96:] = (20, 20, 200)
    return {
        "solid_white": _solid((255, 255, 255)),
        "solid_red": _solid((220, 20, 20)),
        "mix_80_20": mixture,
        "grayscale_gradient": gradient,
        "letterboxed_green": letterboxed,
        "three_colours": three,
    }


def render(path: Path = OUTPUT) -> Path:
    """Analyze each golden frame and write a standalone HTML review page."""
    analyzer = OpenCvChromaticAnalyzer()
    config = AnalysisConfig().chromatic
    sections: list[str] = []
    for name, rgb in golden_frames().items():
        result = analyzer.analyze_shot(
            (ChromaticFrame(sample_id=uuid4(), jpeg=_jpeg(rgb)),),
            config,
        )
        swatches = ""
        lighting = "n/a"
        usable = "n/a"
        if result.value is not None:
            lighting = result.value.lighting_key.value
            usable = f"{result.value.usable_pixel_ratio:.3f}"
            for swatch in result.value.palette:
                swatches += (
                    "<div style='display:inline-block;margin:4px;text-align:center'>"
                    f"<div style='width:64px;height:64px;background:{swatch.rgb.hex};"
                    "border:1px solid #333'></div>"
                    f"<div>{html.escape(swatch.rgb.hex)}</div>"
                    f"<div>{swatch.proportion:.3f}</div></div>"
                )
        sections.append(
            f"<section><h2>{html.escape(name)}</h2>"
            f"<p>status={html.escape(result.status.value)} lighting={html.escape(lighting)} "
            f"usable={html.escape(usable)}</p>{swatches}</section>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Chromatic goldens</title>"
        "</head><body><h1>Chromatic golden review</h1>" + "".join(sections) + "</body></html>",
        encoding="utf-8",
    )
    return path


def main() -> int:
    """CLI entry: write build/chromatic-goldens.html."""
    written = render()
    print(f"wrote {written}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
