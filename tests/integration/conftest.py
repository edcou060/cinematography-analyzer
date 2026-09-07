"""Integration conftest. Shared media clips come from ``tests/conftest.py``."""

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from cine_analyzer.adapters.persistence.postgres import PostgresJobRepository

REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _bin(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    prefixes = [
        Path("/opt/homebrew/opt/postgresql@16/bin"),
        Path("/usr/local/opt/postgresql@16/bin"),
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
    ]
    cellar_roots = (
        Path("/opt/homebrew/Cellar/postgresql@16"),
        Path("/usr/local/Cellar/postgresql@16"),
    )
    for cellar in cellar_roots:
        if cellar.is_dir():
            prefixes.extend(sorted(cellar.glob("*/bin"), reverse=True))
    for prefix in prefixes:
        candidate = prefix / name
        if candidate.is_file():
            return str(candidate)
    return None


@pytest.fixture(scope="session")
def postgres_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Use PYTEST_POSTGRES_URL or start a throwaway PostgreSQL data directory."""
    existing = os.environ.get("PYTEST_POSTGRES_URL")
    if existing:
        env = os.environ.copy()
        env["CINE_DATABASE_URL"] = existing
        migrated = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if migrated.returncode != 0:
            pytest.skip(f"alembic upgrade failed: {migrated.stderr}\n{migrated.stdout}")
        yield existing
        return
    initdb = _bin("initdb")
    pg_ctl = _bin("pg_ctl")
    createdb = _bin("createdb")
    if initdb is None or pg_ctl is None or createdb is None:
        pytest.skip("PostgreSQL initdb/pg_ctl/createdb are required for Phase 08 tests")
    data = tmp_path_factory.mktemp("pgdata")
    port = _free_port()
    subprocess.run(
        [
            initdb,
            "-D",
            str(data),
            "--username=cine",
            "--auth-local=trust",
            "--auth-host=trust",
            "--encoding=UTF8",
            "--locale=C",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "LANG": "C", "LC_ALL": "C"},
    )
    log_file = data / "pg.log"
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-l",
            str(log_file),
            "-o",
            f"-p {port} -k {data}",
            "start",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    url = f"postgresql+pg8000://cine:@127.0.0.1:{port}/cine_analyzer"
    try:
        created = None
        deadline = time.time() + 20
        while time.time() < deadline:
            created = subprocess.run(
                [createdb, "-h", "127.0.0.1", "-p", str(port), "-U", "cine", "cine_analyzer"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if created.returncode == 0:
                break
            time.sleep(0.25)
        else:
            detail = "" if created is None else created.stderr
            pytest.skip(f"createdb failed: {detail}")
        env = os.environ.copy()
        env["CINE_DATABASE_URL"] = url
        migrated = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if migrated.returncode != 0:
            pytest.skip(f"alembic upgrade failed: {migrated.stderr}\n{migrated.stdout}")
        yield url
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "fast", "stop"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


@pytest.fixture
def pg_repo(postgres_url: str) -> Iterator[PostgresJobRepository]:
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE critique_runs, report_summaries, shots, stage_runs, "
                "artifacts, analyses, videos RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
    repo = PostgresJobRepository(postgres_url)
    try:
        yield repo
    finally:
        repo.close()
