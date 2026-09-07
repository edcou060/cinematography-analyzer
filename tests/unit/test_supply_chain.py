"""Lockfile posture.

ADR-0008 requires a check, from this phase onward, that no base-install
dependency carries a licence incompatible with Apache-2.0 distribution, and that
`THIRD_PARTY_NOTICES.md` is derived from `uv.lock` rather than from memory.
Release checklist item P5 additionally requires that no `ultralytics` node exists
in the resolution, even transitively.

The check fails closed. An unrecognised licence declaration is a failure that
asks a human to look, not a value the test quietly accepts.
"""

import json
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from packaging.markers import Marker

from cine_analyzer.diagnostics import SUPPORTED_PYTHON_SPECIFIER

ROOT_PACKAGE = "cine-analyzer"
NOTICES_HEADING = "## Base installation dependencies"

# Exact declaration strings, matched literally. Widening this set is a deliberate
# act with a licence review behind it, which is the point of listing them.
PERMISSIVE_DECLARATIONS = frozenset(
    {
        "0BSD",
        "Apache 2.0",
        "Apache-2.0",
        "Apache-2.0 OR MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSD 3-Clause License",
        "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
        "Dual License",
        "ISC",
        "License :: OSI Approved :: BSD License",
        "MIT",
        "MIT AND PSF-2.0",
        "MIT No Attribution",
        "MIT OR Apache-2.0",
        "MPL-2.0",
        "MPL-2.0 AND MIT",
        "PSF-2.0",
    },
)

# The licence gate this project exists on the right side of; see ADR-0007.
GATED_OUT_OF_BASE_INSTALL = ("ultralytics",)

_MAX_DECLARATION_LENGTH = 80


@pytest.fixture(scope="module")
def lock(repo_root: Path) -> dict[str, Any]:
    parsed: dict[str, Any] = tomllib.loads((repo_root / "uv.lock").read_text(encoding="utf-8"))
    return parsed


@pytest.fixture(scope="module")
def packages(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {package["name"]: package for package in lock["package"]}


def _runtime_dependencies(package: dict[str, Any]) -> list[str]:
    """Lockfile edges that apply on this interpreter and platform."""
    names: list[str] = []
    for dep in package.get("dependencies", []):
        marker = dep.get("marker")
        if marker is not None and not Marker(marker).evaluate():
            continue
        names.append(dep["name"])
    return names


@pytest.fixture(scope="module")
def base_closure(packages: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Every package the base install pulls in, transitively, with its resolved version."""
    pending = _runtime_dependencies(packages[ROOT_PACKAGE])
    resolved: dict[str, str] = {}
    while pending:
        name = pending.pop()
        if name in resolved:
            continue
        package = packages[name]
        resolved[name] = package["version"]
        pending.extend(_runtime_dependencies(package))
    return resolved


def _declared_license(distribution: str) -> str:
    """Read the licence a package declares about itself, in preference order."""
    package_metadata = metadata.metadata(distribution)

    expression = package_metadata.get("License-Expression")
    if expression:
        return expression.strip()

    legacy = package_metadata.get("License")
    if legacy and "\n" not in legacy and len(legacy) <= _MAX_DECLARATION_LENGTH:
        return legacy.strip()

    classifiers = [
        line for line in package_metadata.get_all("Classifier") or [] if line.startswith("License ")
    ]
    return "; ".join(classifiers)


def _notices_rows(repo_root: Path) -> dict[str, tuple[str, str]]:
    """Parse the generated table into ``{package: (version, licence)}``."""
    text = (repo_root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    section = text.split(NOTICES_HEADING, 1)[1].split("\n## ", 1)[0]

    rows: dict[str, tuple[str, str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] in {"Package", ""} or set(cells[0]) <= {"-", ":"}:
            continue
        rows[cells[0].strip("`")] = (cells[1].strip("`"), cells[2])
    return rows


def test_the_lockfile_is_committed(repo_root: Path) -> None:
    assert (repo_root / "uv.lock").is_file()


def test_the_base_install_pulls_in_only_what_this_phase_uses(base_closure: dict[str, str]) -> None:
    """Direct additions are visible in pyproject; this pins the transitive closure too."""
    assert sorted(base_closure) == [
        "alembic",
        "annotated-doc",
        "annotated-types",
        "anyio",
        "asn1crypto",
        "av",
        "certifi",
        "click",
        "cloudpickle",
        "fastapi",
        "greenlet",
        "h11",
        "httpcore",
        "httpx",
        "idna",
        "joblib",
        "mako",
        "markupsafe",
        "narwhals",
        "numpy",
        "opencv-python",
        "pg8000",
        "platformdirs",
        "pydantic",
        "pydantic-core",
        "pydantic-settings",
        "python-dateutil",
        "python-dotenv",
        "python-multipart",
        "scenedetect",
        "scikit-learn",
        "scipy",
        "scramp",
        "six",
        "sqlalchemy",
        "starlette",
        "structlog",
        "threadpoolctl",
        "tqdm",
        "typing-extensions",
        "typing-inspection",
        "uvicorn",
    ]


@pytest.mark.parametrize("gated", GATED_OUT_OF_BASE_INSTALL)
def test_a_gated_component_appears_nowhere_in_the_resolution(
    packages: dict[str, dict[str, Any]],
    gated: str,
) -> None:
    """Release checklist P5. Not in the base install, and not in a dev group either."""
    assert gated not in packages


def test_every_base_dependency_declares_a_licence_this_project_can_distribute(
    base_closure: dict[str, str],
) -> None:
    """ADR-0008. Declarations are read from installed metadata, never recalled."""
    offenders = {
        name: _declared_license(name)
        for name in base_closure
        if _declared_license(name) not in PERMISSIVE_DECLARATIONS
    }

    assert offenders == {}, (
        f"Base dependencies with an unreviewed licence declaration: {offenders}. "
        "Either confirm the declaration is compatible with Apache-2.0 distribution and add "
        "it to PERMISSIVE_DECLARATIONS, or gate the dependency out of the base install."
    )


def test_the_notices_table_matches_the_resolved_base_install(
    repo_root: Path,
    base_closure: dict[str, str],
) -> None:
    """THIRD_PARTY_NOTICES.md is derived from uv.lock, so drift is a test failure."""
    expected = {
        name: (version, _declared_license(name)) for name, version in sorted(base_closure.items())
    }

    assert _notices_rows(repo_root) == expected, (
        "THIRD_PARTY_NOTICES.md is out of date. Expected rows:\n"
        + "\n".join(
            f"| `{name}` | `{version}` | {licence} |"
            for name, (version, licence) in expected.items()
        )
    )


def test_the_declared_python_baseline_is_stated_once(repo_root: Path) -> None:
    """``doctor`` reports the same range the build metadata enforces."""
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == SUPPORTED_PYTHON_SPECIFIER


def test_the_version_has_a_single_source_of_truth(repo_root: Path) -> None:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "src/cine_analyzer/__init__.py"


def test_the_committed_sbom_matches_the_base_install(
    repo_root: Path,
    base_closure: dict[str, str],
) -> None:
    """CycloneDX document is the same lockfile closure as THIRD_PARTY_NOTICES.md."""
    payload = json.loads((repo_root / "docs" / "examples" / "sbom-cyclonedx.json").read_text())
    assert payload["bomFormat"] == "CycloneDX"
    assert payload["metadata"]["component"]["name"] == "cine-analyzer"
    assert payload["metadata"]["component"]["version"] == "0.1.0"
    found = {item["name"]: item["version"] for item in payload["components"]}
    assert found == base_closure
