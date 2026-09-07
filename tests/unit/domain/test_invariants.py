"""Identifier, unit, and isolation rules that apply to the whole domain package."""

import ast
import inspect
import json
import subprocess
import sys
import types
from enum import Enum
from pathlib import Path
from typing import Annotated, Union, get_args, get_origin

from cine_analyzer import domain as domain_package
from cine_analyzer.domain.jobs import StageCommand, StageResult
from cine_analyzer.domain.report import VideoSummary
from cine_analyzer.domain.types import StrictModel

FORBIDDEN_SOURCE_TOKENS = (
    "fastapi",
    "celery",
    "sqlalchemy",
    "streamlit",
    "cv2",
    "torch",
    "ultralytics",
    "sklearn",
)

FLOAT_MS_ALLOWLIST = frozenset({"average_shot_length_ms", "median_shot_length_ms"})


def _domain_root() -> Path:
    return Path(inspect.getfile(domain_package)).resolve().parent


def _iter_domain_models() -> list[type[StrictModel]]:
    return [
        obj
        for obj in vars(domain_package).values()
        if isinstance(obj, type) and issubclass(obj, StrictModel) and obj is not StrictModel
    ]


def _annotation_types(annotation: object) -> list[type[object]]:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _annotation_types(get_args(annotation)[0])
    if origin in {Union, types.UnionType}:
        collected: list[type[object]] = []
        for arg in get_args(annotation):
            collected.extend(_annotation_types(arg))
        return collected
    if annotation is type(None):
        return []
    if isinstance(annotation, type):
        return [annotation]
    return []


def test_scene_is_not_a_domain_identifier() -> None:
    """Detected intervals are shots. The reserved grouping name is not a field or type."""
    for model in _iter_domain_models():
        assert "scene" not in model.__name__.lower()
        for field_name in model.model_fields:
            assert "scene" not in field_name.lower()
    for obj in vars(domain_package).values():
        if isinstance(obj, type) and issubclass(obj, Enum) and obj is not Enum:
            for member in obj:
                assert "scene" not in member.name.lower()
                assert "scene" not in str(member.value).lower()


def test_durable_time_fields_use_integer_milliseconds() -> None:
    """ADR-0006. VideoSummary aggregates are the documented float exception in data-contracts §9."""
    offenders: list[str] = []
    for model in _iter_domain_models():
        for name, field in model.model_fields.items():
            types_found = _annotation_types(field.annotation)
            if name.endswith("_ms"):
                if name in FLOAT_MS_ALLOWLIST:
                    assert float in types_found, f"{model.__name__}.{name} should be float"
                    continue
                if int not in types_found:
                    offenders.append(f"{model.__name__}.{name} types={types_found}")
            if name.endswith(("_s", "_sec", "_secs", "_seconds")):
                offenders.append(f"{model.__name__}.{name} looks like seconds")
    assert offenders == []
    assert "average_shot_length_ms" in VideoSummary.model_fields
    assert "median_shot_length_ms" in VideoSummary.model_fields


def test_domain_sources_do_not_name_infrastructure() -> None:
    hits: list[str] = []
    for path in _domain_root().rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        hits.extend(f"{path.name}:{token}" for token in FORBIDDEN_SOURCE_TOKENS if token in text)
    assert hits == []


def test_domain_modules_import_no_infrastructure_packages() -> None:
    """Importing domain in a fresh interpreter must not load adapter libraries."""
    probe = (
        "import json, sys\n"
        "import cine_analyzer.domain\n"
        "forbidden = ("
        "'fastapi', 'celery', 'sqlalchemy', 'streamlit', 'cv2', 'torch', "
        "'ultralytics', 'numpy'"
        ")\n"
        "sys.stdout.write(json.dumps(sorted(name for name in forbidden if name in sys.modules)))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert json.loads(completed.stdout) == []


def test_queue_payloads_have_no_path_or_bytes_fields() -> None:
    for model in (StageCommand, StageResult):
        for name, field in model.model_fields.items():
            assert "path" not in name.lower()
            assert "frame" not in name.lower()
            types_found = _annotation_types(field.annotation)
            assert bytes not in types_found
            assert bytearray not in types_found


def test_domain_package_parses_as_pure_python() -> None:
    for path in _domain_root().rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))
