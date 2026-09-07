"""Optional critic adapters. No Ollama or vLLM package."""

from cine_analyzer.adapters.critic.fake import FakeCritic
from cine_analyzer.adapters.critic.noop import NoOpCritic
from cine_analyzer.adapters.critic.openai_compat import OpenAICompatCritic

__all__ = ["FakeCritic", "NoOpCritic", "OpenAICompatCritic"]
