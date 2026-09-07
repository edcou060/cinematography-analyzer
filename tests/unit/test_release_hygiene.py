"""Release hygiene: no tracked media, no obvious secrets, honest vocabulary."""

import re
from pathlib import Path

from tests.conftest import REPO_ROOT

_MEDIA_SUFFIXES = (
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".wav",
    ".mp3",
    ".pt",
    ".pth",
    ".onnx",
    ".sqlite",
    ".db",
)
_SECRET = re.compile(
    r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|AKIA[0-9A-Z]{16}|sk-live-[A-Za-z0-9]+"
)
_HOST_PATH = re.compile(r"/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+")


def _tracked_files() -> list[Path]:
    import subprocess

    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [REPO_ROOT / line for line in completed.stdout.splitlines() if line]


def test_no_media_weights_or_databases_are_tracked() -> None:
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _tracked_files()
        if path.suffix.lower() in _MEDIA_SUFFIXES
    ]
    assert offenders == []


def test_tracked_text_has_no_private_key_or_live_token_blobs() -> None:
    hits: list[str] = []
    for path in _tracked_files():
        if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".svg", ".json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _SECRET.search(text):
            hits.append(path.relative_to(REPO_ROOT).as_posix())
    assert hits == []


def test_published_examples_do_not_embed_host_paths() -> None:
    for relative in (
        "docs/examples/sample-report.json",
        "docs/examples/release-benchmark.json",
        "docs/examples/sbom-cyclonedx.json",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert _HOST_PATH.search(text) is None, relative


def test_readme_keeps_measurement_vocabulary() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "narrative scene" in text
    assert "not narrative scenes" in text or "not a semantic" in text
    assert "detector_not_installed" in text
    assert "tension is a proxy" in text or "tension proxy" in text
