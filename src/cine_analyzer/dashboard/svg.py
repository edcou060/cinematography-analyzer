"""SVG snapshots for README / visual QA. Same geometry the Streamlit charts use."""

from cine_analyzer.dashboard.transforms import (
    PaletteBar,
    ShotBar,
    TensionSeries,
    format_timecode,
    subject_schematic,
)
from cine_analyzer.domain.spatial import SpatialValue

__all__ = [
    "composition_svg",
    "hash_wrap_svg",
    "palette_svg",
    "shot_timeline_svg",
    "tension_svg",
]


def _svg_open(width: int, height: int, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'role="img" aria-label="{label}">'
    )


def palette_svg(bars: tuple[PaletteBar, ...], *, width: int = 640, height: int = 72) -> str:
    """Proportion-sized swatches with exact hex labels that wrap if long."""
    cursor = 0.0
    chunks = [_svg_open(width, height, "Palette proportions")]
    for bar in bars:
        span = width * (bar.width_pct / 100.0)
        chunks.append(
            f'<rect x="{cursor:.2f}" y="0" width="{span:.2f}" height="40" fill="{bar.hex_color}"/>'
        )
        label = f"{bar.hex_color} · {bar.width_pct:.1f}%"
        chunks.append(
            f'<text x="{cursor + 4:.2f}" y="60" font-size="11" font-family="monospace" '
            f'style="overflow-wrap:anywhere">{label}</text>'
        )
        cursor += span
    chunks.append("</svg>")
    return "".join(chunks)


def shot_timeline_svg(bars: tuple[ShotBar, ...], *, width: int = 640, height: int = 80) -> str:
    """Detected shot intervals along the clip. Not narrative scenes."""
    if not bars:
        return _svg_open(width, height, "No shots") + "</svg>"
    duration = max(bar.end_ms for bar in bars)
    duration = max(duration, 1)
    chunks = [_svg_open(width, height, "Detected shot intervals")]
    colors = ("#4C6EF5", "#15AABF", "#82C91E", "#FAB005", "#FD7E14")
    for bar in bars:
        x = width * (bar.start_ms / duration)
        w = max(2.0, width * (bar.duration_ms / duration) - 1)
        color = colors[bar.index % len(colors)]
        chunks.append(
            f'<rect x="{x:.2f}" y="8" width="{w:.2f}" height="32" fill="{color}" opacity="0.85"/>'
        )
        stamp = format_timecode(bar.start_ms)
        chunks.append(f'<text x="{x + 2:.2f}" y="60" font-size="10">{bar.index} {stamp}</text>')
    chunks.append("</svg>")
    return "".join(chunks)


def tension_svg(series: TensionSeries, *, width: int = 640, height: int = 180) -> str:
    """Component polylines. Combined proxy is drawn last."""
    label = f"Tension proxy components, method {series.method_version}"
    chunks = [_svg_open(width, height, label)]
    if not series.at_ms:
        chunks.append("</svg>")
        return "".join(chunks)
    start = series.at_ms[0]
    span = max(1, series.at_ms[-1] - start)

    def _poly(values: tuple[float, ...], color: str) -> str:
        pairs: list[str] = []
        for at_ms, value in zip(series.at_ms, values, strict=True):
            x = (at_ms - start) / span * (width - 16) + 8
            y = height - 24 - value * (height - 40)
            pairs.append(f"{x:.1f},{y:.1f}")
        joined = " ".join(pairs)
        return f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{joined}"/>'

    chunks.append(_poly(series.cut_activity, "#4C6EF5"))
    chunks.append(_poly(series.audio_activity, "#82C91E"))
    chunks.append(_poly(series.motion_activity, "#FAB005"))
    chunks.append(_poly(series.combined_proxy, "#212529"))
    for boundary in series.shot_boundary_ms:
        x = (boundary - start) / span * (width - 16) + 8
        chunks.append(
            f'<line x1="{x:.1f}" y1="8" x2="{x:.1f}" y2="{height - 16}" '
            f'stroke="#868E96" stroke-dasharray="4 3"/>'
        )
    version = series.method_version
    chunks.append(f'<text x="8" y="{height - 4}" font-size="10">{version} · tension proxy</text>')
    chunks.append("</svg>")
    return "".join(chunks)


def composition_svg(value: SpatialValue | None, *, width: int = 320, height: int = 180) -> str:
    """Thirds/centre guides and an optional schematic subject rectangle."""
    chunks = [
        _svg_open(width, height, "Composition guides"),
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#111"/>',
    ]
    for fraction in (1 / 3, 2 / 3):
        x = width * fraction
        y = height * fraction
        chunks.append(
            f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{height}" stroke="#FA5252" opacity="0.7"/>'
        )
        chunks.append(
            f'<line x1="0" y1="{y:.1f}" x2="{width}" y2="{y:.1f}" stroke="#FA5252" opacity="0.7"/>'
        )
    chunks.append(f'<circle cx="{width / 2:.1f}" cy="{height / 2:.1f}" r="4" fill="#E9ECEF"/>')
    if value is None:
        chunks.append(
            '<text x="8" y="20" fill="#E9ECEF" font-size="11">'
            "no person / spatial unavailable</text>"
        )
    else:
        box = subject_schematic(value)
        chunks.append(
            f'<rect x="{box["x"] * width:.1f}" y="{box["y"] * height:.1f}" '
            f'width="{box["width"] * width:.1f}" height="{box["height"] * height:.1f}" '
            f'fill="none" stroke="#22B8CF" stroke-width="2"/>'
        )
    chunks.append("</svg>")
    return "".join(chunks)


def hash_wrap_svg(text: str, *, width: int = 320, height: int = 48) -> str:
    """Monospace identifier that wraps rather than overflowing the layout."""
    return (
        _svg_open(width, height, "Wrapping identifier")
        + f'<text x="8" y="20" font-size="11" font-family="monospace" '
        f'style="overflow-wrap:anywhere">{text}</text></svg>'
    )
