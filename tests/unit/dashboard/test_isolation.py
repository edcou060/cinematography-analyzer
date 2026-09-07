"""Dashboard imports stay free of workers, persistence, and CV libraries."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_SRC = ROOT / "src" / "cine_analyzer" / "dashboard"
APP_PATH = ROOT / "apps" / "dashboard" / "app.py"

_FORBIDDEN_EVERYWHERE = frozenset(
    {
        "cv2",
        "av",
        "scenedetect",
        "sqlalchemy",
        "ultralytics",
        "torch",
    }
)
_FORBIDDEN_LIBRARY = _FORBIDDEN_EVERYWHERE | frozenset({"streamlit", "plotly"})
_FORBIDDEN_APP_MODULES = (
    "cine_analyzer.application.wiring",
    "cine_analyzer.application.report",
    "cine_analyzer.worker",
    "cine_analyzer.adapters.persistence",
    "cine_analyzer.adapters.vision",
)


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module.split(".", 1)[0])
            names.add(node.module)
    return names


def test_library_helpers_do_not_import_streamlit_or_cv() -> None:
    offenders: list[str] = []
    for path in DASHBOARD_SRC.glob("*.py"):
        hits = _imported_roots(path) & _FORBIDDEN_LIBRARY
        offenders.extend(f"{path.name}:{name}" for name in sorted(hits))
    assert offenders == []


def test_streamlit_app_does_not_import_workers_or_cv() -> None:
    names = _imported_roots(APP_PATH)
    hits = names & _FORBIDDEN_EVERYWHERE
    module_hits = [item for item in _FORBIDDEN_APP_MODULES if item in names]
    assert sorted(hits) == []
    assert module_hits == []


def test_importing_the_dashboard_package_does_not_load_cv_or_workers() -> None:
    script = """
import sys
import cine_analyzer.dashboard
assert "cv2" not in sys.modules
assert "av" not in sys.modules
assert "scenedetect" not in sys.modules
assert "streamlit" not in sys.modules
assert "plotly" not in sys.modules
assert "cine_analyzer.application.wiring" not in sys.modules
assert "cine_analyzer.application.report" not in sys.modules
assert "cine_analyzer.worker" not in sys.modules
assert "cine_analyzer.adapters.persistence.postgres" not in sys.modules
assert "cine_analyzer.adapters.vision.opencv_chromatics" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
