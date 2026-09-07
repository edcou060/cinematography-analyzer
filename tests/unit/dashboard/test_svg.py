"""SVG snapshots used by visual QA and the README."""

from pathlib import Path

from tests.factories import (
    ANALYSIS_ID,
    DIGEST,
    make_report,
    make_shot,
    make_shot_analysis,
    make_spatial_value,
    make_swatch,
)
from tests.unit.domain.test_timeline import _point

from cine_analyzer.api.schemas import TimelineWindowResponse
from cine_analyzer.dashboard.svg import (
    composition_svg,
    hash_wrap_svg,
    palette_svg,
    shot_timeline_svg,
    tension_svg,
)
from cine_analyzer.dashboard.transforms import palette_bars, shot_bars, tension_series
from cine_analyzer.domain.report import VideoSummary

_IMAGES = Path(__file__).resolve().parents[3] / "docs" / "images" / "dashboard"


def _many_shot_report(count: int = 24) -> object:
    analyses = tuple(
        make_shot_analysis(make_shot(index=index, start_ms=index * 80, end_ms=index * 80 + 80))
        for index in range(count)
    )
    return make_report(
        shots=analyses,
        summary=VideoSummary(
            shot_count=count,
            average_shot_length_ms=80.0,
            median_shot_length_ms=80.0,
            shots_per_minute=750.0,
        ),
    )


def test_palette_svg_sizes_swatches_and_prints_hex() -> None:
    bars = palette_bars(
        (
            make_swatch(rank=1, proportion=0.6, red=16, green=32, blue=48),
            make_swatch(rank=2, proportion=0.4, red=200, green=10, blue=10),
        )
    )
    markup = palette_svg(bars)
    assert "#102030" in markup
    assert "60.0%" in markup
    assert palette_svg(()) == (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="72" '
        'role="img" aria-label="Palette proportions"></svg>'
    )


def test_shot_timeline_svg_handles_empty_and_dense_intervals() -> None:
    assert "No shots" in shot_timeline_svg(())
    report = _many_shot_report()
    markup = shot_timeline_svg(shot_bars(report))  # type: ignore[arg-type]
    assert "Detected shot intervals" in markup
    assert markup.count("<rect") == 24


def test_tension_svg_draws_components_or_an_empty_frame() -> None:
    empty = tension_series(
        TimelineWindowResponse(
            analysis_id=ANALYSIS_ID,
            start_ms=0,
            end_ms=1,
            max_points=10,
            points=(),
        ),
        make_report(),
    )
    assert tension_svg(empty).endswith("</svg>")
    first = make_shot(index=0, start_ms=0, end_ms=2000)
    second = make_shot(index=1, start_ms=2000, end_ms=4000)
    report = make_report(
        shots=(make_shot_analysis(first), make_shot_analysis(second)),
        summary=VideoSummary(
            shot_count=2,
            average_shot_length_ms=2000.0,
            median_shot_length_ms=2000.0,
            shots_per_minute=30.0,
        ),
    )
    series = tension_series(
        TimelineWindowResponse(
            analysis_id=ANALYSIS_ID,
            start_ms=0,
            end_ms=4000,
            max_points=10,
            points=(_point(0), _point(1000), _point(2000)),
        ),
        report,
    )
    markup = tension_svg(series)
    assert "tension-v1" in markup
    assert markup.count("<polyline") == 4
    assert "<line" in markup


def test_composition_svg_shows_guides_with_and_without_a_subject() -> None:
    missing = composition_svg(None)
    assert "no person / spatial unavailable" in missing
    present = composition_svg(make_spatial_value())
    assert "#22B8CF" in present


def test_hash_wrap_svg_contains_the_full_digest() -> None:
    markup = hash_wrap_svg(DIGEST)
    assert DIGEST in markup
    assert "overflow-wrap:anywhere" in markup


def test_visual_qa_svg_files_match_the_helpers() -> None:
    """README images are generated from the same helpers the UI uses."""
    bars = palette_bars((make_swatch(rank=1, proportion=1.0, red=16, green=32, blue=48),))
    first = make_shot(index=0, start_ms=0, end_ms=2000)
    second = make_shot(index=1, start_ms=2000, end_ms=4000)
    report = make_report(
        shots=(make_shot_analysis(first), make_shot_analysis(second)),
        summary=VideoSummary(
            shot_count=2,
            average_shot_length_ms=2000.0,
            median_shot_length_ms=2000.0,
            shots_per_minute=30.0,
        ),
    )
    series = tension_series(
        TimelineWindowResponse(
            analysis_id=ANALYSIS_ID,
            start_ms=0,
            end_ms=4000,
            max_points=10,
            points=(_point(0), _point(2000)),
        ),
        report,
    )
    expected = {
        "palette.svg": palette_svg(bars),
        "shot-timeline.svg": shot_timeline_svg(shot_bars(report)),
        "many-shots.svg": shot_timeline_svg(shot_bars(_many_shot_report())),  # type: ignore[arg-type]
        "tension.svg": tension_svg(series),
        "composition.svg": composition_svg(make_spatial_value()),
        "composition-empty.svg": composition_svg(None),
        "hash-wrap.svg": hash_wrap_svg(DIGEST),
    }
    for name, markup in expected.items():
        path = _IMAGES / name
        assert path.is_file(), f"missing {path}"
        assert path.read_text(encoding="utf-8") == markup
