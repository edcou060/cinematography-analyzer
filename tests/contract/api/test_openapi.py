"""OpenAPI snapshot for the public control plane."""

import json
from pathlib import Path

from cine_analyzer.api.app import OPENAPI_SNAPSHOT, create_app


def test_openapi_snapshot_matches() -> None:
    rendered = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    assert OPENAPI_SNAPSHOT.is_file(), rendered
    assert OPENAPI_SNAPSHOT.read_text(encoding="utf-8") == rendered


def test_snapshot_lives_in_the_contract_tree() -> None:
    assert Path(__file__).resolve().parent / "openapi.json" == OPENAPI_SNAPSHOT
