"""Importing the worker package must not load Celery or CV libraries."""

import subprocess
import sys


def test_worker_package_import_does_not_load_celery_or_cv() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            (
                "import sys; import cine_analyzer.worker; "
                "mods = set(sys.modules); "
                "assert 'celery' not in mods; "
                "assert 'cv2' not in mods; "
                "assert 'av' not in mods; "
                "assert 'redis' not in mods"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
