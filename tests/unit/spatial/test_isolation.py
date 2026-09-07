"""Application and port spatial modules stay detector-SDK free."""

import ast
import inspect
from pathlib import Path

from cine_analyzer.application import (
    framing,
    spatial,
    spatial_geometry,
    spatial_select,
    spatial_track,
)
from cine_analyzer.ports import spatial as spatial_ports

_FORBIDDEN = frozenset({"cv2", "numpy", "ultralytics", "torch", "sklearn"})


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module.split(".", 1)[0])
    return names


def test_spatial_application_and_ports_do_not_import_detector_sdks() -> None:
    modules = (spatial, spatial_geometry, spatial_select, spatial_track, framing, spatial_ports)
    offenders: list[str] = []
    for module in modules:
        path = Path(inspect.getfile(module))
        hits = _imported_roots(path) & _FORBIDDEN
        offenders.extend(f"{path.name}:{name}" for name in sorted(hits))
    assert offenders == []
