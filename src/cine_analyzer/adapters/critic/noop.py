"""No-op critic. Interpretation is omitted; analysis is unchanged."""

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.critic import CriticInput

__all__ = ["NoOpCritic"]


class NoOpCritic:
    """Disabled or unconfigured adapter. ``complete`` never talks to a model."""

    def __init__(self, identity: str = "none:disabled") -> None:
        self._identity = identity

    def identity(self) -> str:
        return self._identity

    def complete(self, prompt: str, payload: CriticInput, *, timeout_ms: int) -> str:
        del prompt, payload, timeout_ms
        raise AdapterError(
            "MODEL_UNAVAILABLE",
            "the critic adapter is not configured",
            retryable=False,
            stage="critic",
        )
