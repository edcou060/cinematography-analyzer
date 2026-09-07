"""Generate tiny local media fixtures.

The mp4 files are gitignored. This script is the committed source of the clips
used by Phase 03 ingest tests, Phase 04 shot-detection goldens, and the Phase 06
composition-grid spatial fixture. It invokes ffmpeg with an argument array and
never a shell.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "fixtures" / "video"
FFMPEG_TIMEOUT_S = 60


def _ffmpeg() -> str:
    resolved = shutil.which("ffmpeg")
    if resolved is None:
        message = "ffmpeg is not available on PATH; cannot generate fixtures"
        raise RuntimeError(message)
    return resolved


def _run(argv: list[str]) -> None:
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        timeout=FFMPEG_TIMEOUT_S,
        shell=False,
    )
    if completed.returncode != 0:
        message = "ffmpeg failed while generating fixtures"
        raise RuntimeError(message)


def _encode_color(
    ffmpeg: str,
    destination: Path,
    *,
    color: str,
    width: int,
    height: int,
    duration_s: int,
) -> None:
    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={width}x{height}:d={duration_s}:r=25",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(destination),
    ]
    _run(argv)


def _apply_display_rotation(ffmpeg: str, source: Path, destination: Path, *, degrees: int) -> None:
    """Write display-matrix rotation without transcoding pixels."""
    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-display_rotation",
        str(degrees),
        "-i",
        str(source),
        "-c",
        "copy",
        str(destination),
    ]
    _run(argv)


def _two_color_cut(ffmpeg: str, destination: Path) -> None:
    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x240:d=2:r=25",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=320x240:d=2:r=25",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(destination),
    ]
    _run(argv)


def _flash(ffmpeg: str, destination: Path) -> None:
    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x240:d=2:r=25",
        "-f",
        "lavfi",
        "-i",
        "color=c=white:s=320x240:d=0.08:r=25",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=320x240:d=2:r=25",
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(destination),
    ]
    _run(argv)


def _fade(ffmpeg: str, destination: Path) -> None:
    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=320x240:d=2:r=25",
        "-f",
        "lavfi",
        "-i",
        "color=c=white:s=320x240:d=2:r=25",
        "-filter_complex",
        "[0:v][1:v]xfade=transition=fade:duration=1:offset=1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(destination),
    ]
    _run(argv)


def _composition_grid(ffmpeg: str, destination: Path) -> None:
    """Gray field with a magenta person-sized rectangle on a thirds intersection."""
    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x404040:s=320x240:d=4:r=25",
        "-vf",
        "drawbox=x=75:y=20:w=64:h=120:color=magenta:t=fill",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(destination),
    ]
    _run(argv)


def _tension_signals(ffmpeg: str, destination: Path) -> None:
    """Gray moving-box shot, translated background, hard cut at 2000 ms, beeps at 1s and 3s."""
    argv = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x404040:s=320x240:d=2:r=25",
        "-f",
        "lavfi",
        "-i",
        "color=c=white:s=40x40:d=2:r=25",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x304080:s=480x240:d=2:r=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=22050:duration=0.1",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=22050:duration=0.1",
        "-filter_complex",
        (
            "[0:v][1:v]overlay=x=80*t:y=100[v0];"
            "[2:v]crop=320:240:80*t:0[v1];"
            "[v0][v1]concat=n=2:v=1:a=0[v];"
            "[3:a]adelay=1000:all=1,apad=whole_dur=4[a1];"
            "[4:a]adelay=3000:all=1,apad=whole_dur=4[a2];"
            "[a1][a2]amix=inputs=2:duration=longest:normalize=0[a]"
        ),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(destination),
    ]
    _run(argv)


def generate(output_dir: Path = OUTPUT_DIR) -> None:
    """Write the Phase 03-07 fixture set under ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()
    _two_color_cut(ffmpeg, output_dir / "two_color_cut.mp4")
    _encode_color(
        ffmpeg, output_dir / "no_audio.mp4", color="black", width=320, height=240, duration_s=1
    )
    scratch = output_dir / "rotated_90.scratch.mp4"
    try:
        _encode_color(ffmpeg, scratch, color="green", width=320, height=240, duration_s=1)
        _apply_display_rotation(ffmpeg, scratch, output_dir / "rotated_90.mp4", degrees=90)
    finally:
        scratch.unlink(missing_ok=True)
    _encode_color(
        ffmpeg,
        output_dir / "over_width.mp4",
        color="yellow",
        width=640,
        height=240,
        duration_s=1,
    )
    _encode_color(
        ffmpeg, output_dir / "no_cut.mp4", color="green", width=320, height=240, duration_s=4
    )
    _flash(ffmpeg, output_dir / "flash.mp4")
    _fade(ffmpeg, output_dir / "fade.mp4")
    _composition_grid(ffmpeg, output_dir / "composition_grid.mp4")
    _tension_signals(ffmpeg, output_dir / "tension_signals.mp4")
    (output_dir / "corrupt.mp4").write_bytes(b"not a valid media container\n")


def main() -> int:
    """CLI entry for ``python scripts/generate_fixtures.py``."""
    try:
        generate()
    except RuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    sys.stdout.write(f"wrote fixtures under {OUTPUT_DIR}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
