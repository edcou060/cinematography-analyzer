"""Broker readiness. Worker/model checks live on the worker process."""

from cine_analyzer.application.errors import AdapterError

__all__ = ["ping_broker"]


def ping_broker(url: str) -> None:
    """Fail when Redis cannot be reached. redis-py is optional (celery extra)."""
    try:
        import redis  # noqa: PLC0415
    except ImportError as error:
        raise AdapterError(
            "RESOURCE_NOT_READY",
            "the broker client is not installed",
            retryable=True,
            stage="control",
        ) from error
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1.0)
        reply = client.ping()
    except Exception as error:
        raise AdapterError(
            "RESOURCE_NOT_READY",
            "the broker is not reachable",
            retryable=True,
            stage="control",
        ) from error
    if not reply:
        raise AdapterError(
            "RESOURCE_NOT_READY",
            "the broker is not reachable",
            retryable=True,
            stage="control",
        )
