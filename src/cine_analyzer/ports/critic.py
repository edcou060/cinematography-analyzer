"""Optional critic port. Adapters emit prose; they cannot write metrics."""

from typing import Protocol

from cine_analyzer.domain.critic import CriticInput

__all__ = ["Critic"]


class Critic(Protocol):
    """Complete a bounded prompt over CriticInput. Timeouts stay in the adapter."""

    def identity(self) -> str:
        """Stable adapter/model identity included in the cache key."""

    def complete(self, prompt: str, payload: CriticInput, *, timeout_ms: int) -> str:
        """Return model text (JSON object with sentences). Raise AdapterError on failure."""
