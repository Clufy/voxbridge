import json
import pathlib

import httpx
import pytest
import respx

import voxbridge
from voxbridge.client import VoiceClient
from voxbridge.models import Agent

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
ASSISTANT = json.loads((FX / "assistant.json").read_text())


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        VoiceClient(provider="nope", api_key="k")


def test_selects_vapi() -> None:
    c = VoiceClient(provider="vapi", api_key="k")
    assert type(c._provider).__name__ == "VapiProvider"
    c.close()


def test_public_exports() -> None:
    for name in ("VoiceClient", "Agent", "Call", "Tool", "CallEnded", "WebhookEvent", "AuthError"):
        assert name in voxbridge.__all__
        assert hasattr(voxbridge, name)


@respx.mock
def test_delegates_create_agent() -> None:
    respx.post("https://api.vapi.ai/assistant").mock(
        return_value=httpx.Response(201, json=ASSISTANT)
    )
    c = VoiceClient("vapi", "k")
    a = c.create_agent(
        Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel")
    )
    assert a.id == ASSISTANT["id"]
    c.close()


class _SpyProvider:
    """Records close/aclose so context-manager delegation can be asserted."""

    def __init__(self) -> None:
        self.closed = False
        self.aclosed = False

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.aclosed = True


def test_sync_context_manager_closes_provider() -> None:
    c = VoiceClient("vapi", "k")
    spy = _SpyProvider()
    c._provider = spy  # type: ignore[assignment]
    with c as entered:
        assert entered is c
    assert spy.closed


async def test_async_context_manager_closes_provider() -> None:
    c = VoiceClient("vapi", "k")
    spy = _SpyProvider()
    c._provider = spy  # type: ignore[assignment]
    async with c as entered:
        assert entered is c
    assert spy.aclosed
