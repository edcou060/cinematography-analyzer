"""Fixtures shared by the unit suite.

Two kinds of global state can leak between tests here: ``CINE_*`` environment
variables and structlog's process-wide configuration. Both are reset around
every test so a test never depends on the machine it runs on or on the test that
ran before it.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog

from cine_analyzer.settings import ENV_PREFIX

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "fixtures" / "video"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any ``CINE_*`` variable inherited from the developer's shell."""
    for name in list(os.environ):
        if name.startswith(ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    """Restore structlog defaults and drop bound context around each test."""
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


@pytest.fixture(autouse=True)
def _reset_observability() -> Iterator[None]:
    from cine_analyzer.application.sample_frames import reset_jpeg_cache_stats
    from cine_analyzer.observability.metrics import reset_metrics

    reset_metrics()
    reset_jpeg_cache_stats()
    yield
    reset_metrics()
    reset_jpeg_cache_stats()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path of the repository checkout under test."""
    return REPO_ROOT


def ffmpeg_on_path() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture(scope="session")
def video_fixtures() -> Path:
    """Generate gitignored clips under fixtures/video when ffmpeg is present."""
    if not ffmpeg_on_path():
        pytest.skip("ffmpeg and ffprobe are required for media integration tests")
    marker = FIXTURE_DIR / "two_color_cut.mp4"
    required = (
        "two_color_cut.mp4",
        "no_cut.mp4",
        "flash.mp4",
        "fade.mp4",
        "composition_grid.mp4",
        "tension_signals.mp4",
        "no_audio.mp4",
    )
    if not marker.is_file() or any(not (FIXTURE_DIR / name).is_file() for name in required):
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "generate_fixtures.py")],
            check=False,
            cwd=REPO_ROOT,
            timeout=120,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            pytest.skip(f"fixture generation failed: {completed.stderr.strip()}")
    if not marker.is_file():
        pytest.skip("fixture generation did not produce two_color_cut.mp4")
    for name in required:
        if not (FIXTURE_DIR / name).is_file():
            pytest.skip(f"fixture generation did not produce {name}")
    return FIXTURE_DIR
