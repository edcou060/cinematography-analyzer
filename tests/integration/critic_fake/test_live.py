"""Optional live OpenAI-compatible smoke. Not required in default CI."""

import os

import pytest

pytestmark = pytest.mark.live_critic


def test_live_openai_compat_smoke() -> None:
    if os.environ.get("CINE_CRITIC_LIVE") != "1":
        pytest.skip("live OpenAI-compatible server not enabled")
