"""Fake, no-op, and OpenAI-compatible HTTP adapters."""

import json

import httpx
import pytest

from cine_analyzer.adapters.critic.fake import FakeCritic
from cine_analyzer.adapters.critic.noop import NoOpCritic
from cine_analyzer.adapters.critic.openai_compat import OpenAICompatCritic
from cine_analyzer.application.critic import CRITIC_SYSTEM_PROMPT
from cine_analyzer.application.errors import AdapterError
from cine_analyzer.domain.critic import (
    CompositionFacts,
    CriticInput,
    CriticOutput,
    EditingFacts,
    LightingFacts,
    TensionFacts,
)


def _input(**overrides: object) -> CriticInput:
    payload: dict[str, object] = {
        "editing": EditingFacts(shot_count=18, asl_seconds=3.42, median_seconds=2.8),
        "lighting": LightingFacts(low_key_ratio=0.62, valid_shot_ratio=0.94),
        "palette": ("#17212B", "#A66B42", "#D5C2A8"),
        "composition": CompositionFacts(valid_shot_ratio=0.71, median_thirds_proximity=0.78),
        "tension_proxy": TensionFacts(peak_seconds=(), audio_available=False),
    }
    payload.update(overrides)
    return CriticInput.model_validate(payload)


def test_fake_covers_palette_peaks_and_thirds() -> None:
    fake = FakeCritic()
    with_palette = fake.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=10)
    parsed = CriticOutput.model_validate_json(with_palette)
    assert 1 <= len(parsed.sentences) <= 3
    both = fake.complete(
        CRITIC_SYSTEM_PROMPT,
        _input(tension_proxy=TensionFacts(peak_seconds=(12.0,), audio_available=True)),
        timeout_ms=10,
    )
    assert "12.0" in both
    assert "Low-key estimate" not in both
    peaks = fake.complete(
        CRITIC_SYSTEM_PROMPT,
        _input(
            palette=(),
            tension_proxy=TensionFacts(peak_seconds=(12.0, 37.5), audio_available=True),
        ),
        timeout_ms=10,
    )
    assert "12.0" in peaks
    assert "Audio features are present" in peaks
    thirds = fake.complete(
        CRITIC_SYSTEM_PROMPT,
        _input(palette=(), tension_proxy=TensionFacts(peak_seconds=(), audio_available=False)),
        timeout_ms=10,
    )
    assert "thirds proximity" in thirds
    lighting = fake.complete(
        CRITIC_SYSTEM_PROMPT,
        _input(
            palette=(),
            composition=CompositionFacts(valid_shot_ratio=0.0, median_thirds_proximity=None),
        ),
        timeout_ms=10,
    )
    assert "Low-key estimate" in lighting
    quiet = fake.complete(
        CRITIC_SYSTEM_PROMPT,
        _input(
            palette=(),
            composition=CompositionFacts(valid_shot_ratio=0.0),
            tension_proxy=TensionFacts(peak_seconds=(12.0,), audio_available=False),
        ),
        timeout_ms=10,
    )
    assert "not present" in quiet


def test_noop_raises_unavailable() -> None:
    with pytest.raises(AdapterError) as caught:
        NoOpCritic().complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=10)
    assert caught.value.code == "MODEL_UNAVAILABLE"


def _openai(
    handler: object, *, api_key: str | None = "secret"
) -> tuple[OpenAICompatCritic, httpx.Client]:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.Client(transport=transport)
    critic = OpenAICompatCritic(
        base_url="http://critic.test",
        model="local",
        api_key=api_key,
        client=http,
    )
    return critic, http


def test_openai_compat_success_timeout_and_errors() -> None:
    seen: dict[str, str] = {}

    def ok_handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        body = json.dumps(
            {
                "sentences": [
                    "The clip has 18 detected shots with mean length 3.42 s and median 2.8 s."
                ]
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    critic, http = _openai(ok_handler)
    text = critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=8000)
    assert "18 detected shots" in text
    assert seen["auth"] == "Bearer secret"
    critic.close()
    http.close()

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.TimeoutException("slow")

    critic, http = _openai(timeout_handler, api_key=None)
    with pytest.raises(AdapterError) as timed:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert timed.value.code == "MODEL_TIMEOUT"
    http.close()

    def connect_handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("down")

    critic, http = _openai(connect_handler)
    with pytest.raises(AdapterError) as down:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert down.value.code == "MODEL_UNAVAILABLE"
    http.close()

    def client_error(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(400, json={"error": "bad"})

    critic, http = _openai(client_error)
    with pytest.raises(AdapterError) as bad_request:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert bad_request.value.retryable is False
    http.close()

    def server_error(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, json={"error": "busy"})

    critic, http = _openai(server_error)
    with pytest.raises(AdapterError) as busy:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert busy.value.retryable is True
    http.close()

    def junk(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"not-json")

    critic, http = _openai(junk)
    with pytest.raises(AdapterError) as invalid:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert invalid.value.code == "SCHEMA_INVALID"
    http.close()

    def empty_choices(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"choices": []})

    critic, http = _openai(empty_choices)
    with pytest.raises(AdapterError) as missing:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert missing.value.code == "SCHEMA_INVALID"
    http.close()

    def blank(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    critic, http = _openai(blank)
    with pytest.raises(AdapterError) as empty:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert empty.value.code == "SCHEMA_INVALID"
    http.close()

    def not_text(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"choices": [{"message": {"content": 1}}]})

    critic, http = _openai(not_text)
    with pytest.raises(AdapterError) as typed:
        critic.complete(CRITIC_SYSTEM_PROMPT, _input(), timeout_ms=5)
    assert typed.value.code == "SCHEMA_INVALID"
    http.close()

    owned = OpenAICompatCritic(base_url="http://example.invalid/", model="x")
    owned.close()
    owned.close()
