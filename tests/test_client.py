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
    assert voxbridge.VoiceClient
    assert voxbridge.Agent
    assert voxbridge.CallEnded
    assert voxbridge.AuthError


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
