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


def test_all_delegations_forward_to_provider() -> None:
    from unittest.mock import MagicMock

    c = VoiceClient("vapi", "k")
    m = MagicMock()
    c._provider = m  # type: ignore[assignment]

    agent = Agent(name="S", system_prompt="x", model="gpt-4o", voice="v")
    c.create_agent(agent)
    m.create_agent.assert_called_once_with(agent)
    c.update_agent("a1", agent)
    m.update_agent.assert_called_once_with("a1", agent)
    c.get_agent("a1")
    m.get_agent.assert_called_once_with("a1")
    c.delete_agent("a1")
    m.delete_agent.assert_called_once_with("a1")
    c.create_call("a1", "+1", from_number="+2")
    m.create_call.assert_called_once_with("a1", "+1", from_number="+2")
    c.get_call("c1")
    m.get_call.assert_called_once_with("c1")
    c.list_calls()
    m.list_calls.assert_called_once_with()
    c.parse_webhook({"h": "v"}, b"{}")
    m.parse_webhook.assert_called_once_with({"h": "v"}, b"{}")
    c.verify_signature({"h": "v"}, b"{}")
    m.verify_signature.assert_called_once_with({"h": "v"}, b"{}")


async def test_all_async_delegations_forward_to_provider() -> None:
    from unittest.mock import AsyncMock

    c = VoiceClient("vapi", "k")
    m = AsyncMock()
    c._provider = m  # type: ignore[assignment]

    agent = Agent(name="S", system_prompt="x", model="gpt-4o", voice="v")
    await c.acreate_agent(agent)
    m.acreate_agent.assert_awaited_once_with(agent)
    await c.aupdate_agent("a1", agent)
    m.aupdate_agent.assert_awaited_once_with("a1", agent)
    await c.aget_agent("a1")
    m.aget_agent.assert_awaited_once_with("a1")
    await c.adelete_agent("a1")
    m.adelete_agent.assert_awaited_once_with("a1")
    await c.acreate_call("a1", "+1", from_number="+2")
    m.acreate_call.assert_awaited_once_with("a1", "+1", from_number="+2")
    await c.aget_call("c1")
    m.aget_call.assert_awaited_once_with("c1")
    await c.alist_calls()
    m.alist_calls.assert_awaited_once_with()
