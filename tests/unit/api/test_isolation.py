"""API process import isolation: no OpenCV, PyAV, or PySceneDetect."""

import subprocess
import sys


def test_importing_the_api_app_does_not_load_cv_libraries() -> None:
    script = """
import sys
import cine_analyzer.api.app
assert "cv2" not in sys.modules
assert "av" not in sys.modules
assert "scenedetect" not in sys.modules
assert "cine_analyzer.application.wiring" not in sys.modules
assert "cine_analyzer.application.report" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


def test_importing_cli_main_does_not_load_cv_libraries() -> None:
    script = """
import sys
import cine_analyzer.cli.main
assert "cv2" not in sys.modules
assert "av" not in sys.modules
assert "scenedetect" not in sys.modules
assert "cine_analyzer.application.wiring" not in sys.modules
assert "cine_analyzer.application.report" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
