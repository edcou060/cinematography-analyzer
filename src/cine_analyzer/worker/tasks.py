"""Celery ``-A`` entry. ``app`` is built from process settings on first attribute access."""

from typing import Any

__all__: list[str] = []


def __getattr__(name: str) -> Any:
    if name != "app":
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    from cine_analyzer.settings import load_settings
    from cine_analyzer.worker.celery_app import create_celery_app

    return create_celery_app(load_settings())
