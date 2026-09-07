"""OpenAI-compatible HTTP critic via httpx. No provider SDK."""

from typing import Any

import httpx

from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.critic import CriticInput

__all__ = ["OPENAI_TEMPERATURE", "OpenAICompatCritic"]

OPENAI_TEMPERATURE = 0.0
_MAX_TOKENS = 256


class OpenAICompatCritic:
    """POST /v1/chat/completions. Temperature 0. Timeouts map to AdapterError."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._owns = client is None
        self._http = client or httpx.Client()

    def identity(self) -> str:
        return f"openai-compat:{self._model}:temp0:max{_MAX_TOKENS}"

    def close(self) -> None:
        """Close an owned client. Injected transports stay open."""
        if self._owns:
            self._http.close()

    def complete(self, prompt: str, payload: CriticInput, *, timeout_ms: int) -> str:
        headers: dict[str, str] = {"content-type": "application/json"}
        if self._api_key is not None:
            headers["authorization"] = f"Bearer {self._api_key}"
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": OPENAI_TEMPERATURE,
            "max_tokens": _MAX_TOKENS,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": payload.model_dump_json()},
            ],
        }
        url = f"{self._base_url}/v1/chat/completions"
        timeout = httpx.Timeout(timeout_ms / 1000.0)
        try:
            response = self._http.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.TimeoutException as error:
            raise AdapterError(
                "MODEL_TIMEOUT",
                "the critic request timed out",
                retryable=True,
                stage="critic",
            ) from error
        except httpx.HTTPError as error:
            raise AdapterError(
                "MODEL_UNAVAILABLE",
                "the critic endpoint is not reachable",
                retryable=True,
                stage="critic",
            ) from error
        if response.status_code >= 400:
            raise AdapterError(
                "MODEL_UNAVAILABLE",
                "the critic endpoint rejected the request",
                retryable=response.status_code >= 500,
                stage="critic",
            )
        try:
            document = response.json()
            choices = document["choices"]
            message = choices[0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise AdapterError(
                "SCHEMA_INVALID",
                "the critic response was not valid JSON",
                retryable=False,
                stage="critic",
            ) from error
        if not isinstance(content, str) or content.strip() == "":
            raise AdapterError(
                "SCHEMA_INVALID",
                "the critic response did not include text",
                retryable=False,
                stage="critic",
            )
        return content
