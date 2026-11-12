"""Cross-provider parity suite.

Proves that vapi and retell, though wired to completely different wire
formats, hand back the same *domain types* with the same fields populated
for the shared sync surface. Each parametrized case sets up provider-specific
respx routes via a small per-provider helper, then runs identical assertions
against the returned Agent/Call objects.
"""

import hashlib
import hmac
import json
import pathlib
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx

from voxbridge.client import VoiceClient
from voxbridge.events import ToolCall
from voxbridge.models import Agent, Call

VAPI_FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
RETELL_FX = pathlib.Path(__file__).parent / "fixtures" / "retell"

VAPI_ASSISTANT = json.loads((VAPI_FX / "assistant.json").read_text())
VAPI_CALL = json.loads((VAPI_FX / "call.json").read_text())

RETELL_LLM = json.loads((RETELL_FX / "llm.json").read_text())
RETELL_AGENT = json.loads((RETELL_FX / "agent.json").read_text())
RETELL_CALL = json.loads((RETELL_FX / "call.json").read_text())


def _mock_vapi_routes() -> str:
    """Register vapi respx routes for create_agent/get_call/list_calls; return the call id."""
    respx.post("https://api.vapi.ai/assistant").mock(
        return_value=httpx.Response(201, json=VAPI_ASSISTANT)
    )
    respx.get(f"https://api.vapi.ai/call/{VAPI_CALL['id']}").mock(
        return_value=httpx.Response(200, json=VAPI_CALL)
    )
    respx.get("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(200, json=[VAPI_CALL])
    )
    return str(VAPI_CALL["id"])


def _mock_retell_routes() -> str:
    """Register retell respx routes for create_agent/get_call/list_calls; return the call id."""
    respx.post("https://api.retellai.com/create-retell-llm").mock(
        return_value=httpx.Response(201, json=RETELL_LLM)
    )
    respx.post("https://api.retellai.com/create-agent").mock(
        return_value=httpx.Response(201, json=RETELL_AGENT)
    )
    respx.get(f"https://api.retellai.com/v2/get-call/{RETELL_CALL['call_id']}").mock(
        return_value=httpx.Response(200, json=RETELL_CALL)
    )
    respx.post("https://api.retellai.com/v3/list-calls").mock(
        return_value=httpx.Response(200, json={"items": [RETELL_CALL]})
    )
    return str(RETELL_CALL["call_id"])


_ROUTE_SETUP: dict[str, Callable[[], str]] = {
    "vapi": _mock_vapi_routes,
    "retell": _mock_retell_routes,
}


@pytest.mark.parametrize("provider_name", ["vapi", "retell"])
@respx.mock
def test_provider_parity(provider_name: str) -> None:
    call_id = _ROUTE_SETUP[provider_name]()
    client = VoiceClient(provider=provider_name, api_key="k")

    agent = client.create_agent(
        Agent(name="S", system_prompt="be nice", model="gpt-4o", voice="v")
    )
    assert isinstance(agent, Agent)
    assert agent.id

    call = client.get_call(call_id)
    assert isinstance(call, Call)
    assert call.transcript

    calls = client.list_calls()
    assert isinstance(calls, list)
    assert calls
    assert all(isinstance(c, Call) for c in calls)

    client.close()


_AGENT_ID = {"vapi": VAPI_ASSISTANT["id"], "retell": RETELL_AGENT["agent_id"]}


def _echo(base: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """Respond with `base` shallow-merged with the request body, like a real PATCH."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**base, **json.loads(request.content)})

    return handler


def _mock_get_agent(provider_name: str) -> None:
    if provider_name == "vapi":
        respx.get(f"https://api.vapi.ai/assistant/{_AGENT_ID['vapi']}").mock(
            return_value=httpx.Response(200, json=VAPI_ASSISTANT)
        )
        return
    respx.get(f"https://api.retellai.com/get-agent/{_AGENT_ID['retell']}").mock(
        return_value=httpx.Response(200, json=RETELL_AGENT)
    )
    respx.get(
        f"https://api.retellai.com/get-retell-llm/{RETELL_AGENT['response_engine']['llm_id']}"
    ).mock(return_value=httpx.Response(200, json=RETELL_LLM))


@pytest.mark.parametrize("provider_name", ["vapi", "retell"])
@respx.mock
def test_get_agent_parity_carries_prompt(provider_name: str) -> None:
    _mock_get_agent(provider_name)
    with VoiceClient(provider=provider_name, api_key="k") as client:
        agent = client.get_agent(_AGENT_ID[provider_name])
    assert agent.system_prompt
    assert agent.model
    assert agent.voice
    assert agent.voice.lower() == "11labs:rachel"


@pytest.mark.parametrize("provider_name", ["vapi", "retell"])
@respx.mock
def test_update_agent_parity(provider_name: str) -> None:
    _mock_get_agent(provider_name)
    if provider_name == "vapi":
        patch = respx.patch(f"https://api.vapi.ai/assistant/{_AGENT_ID['vapi']}").mock(
            side_effect=_echo(VAPI_ASSISTANT)
        )
        patches = [patch]
    else:
        llm_id = RETELL_AGENT["response_engine"]["llm_id"]
        patches = [
            respx.patch(f"https://api.retellai.com/update-retell-llm/{llm_id}").mock(
                side_effect=_echo(RETELL_LLM)
            ),
            respx.patch(f"https://api.retellai.com/update-agent/{_AGENT_ID['retell']}").mock(
                side_effect=_echo(RETELL_AGENT)
            ),
        ]
    with VoiceClient(provider=provider_name, api_key="k") as client:
        updated = client.update_agent(
            _AGENT_ID[provider_name],
            Agent(
                name="S", system_prompt="brand new prompt", model="gpt-4o",
                voice="elevenlabs:rachel",
            ),
        )
    assert isinstance(updated, Agent)
    assert updated.system_prompt == "brand new prompt"
    assert any(b"brand new prompt" in r.calls.last.request.content for r in patches)


def _retell_signed_tool_request() -> tuple[dict[str, str], bytes]:
    body = (RETELL_FX / "custom_function.json").read_bytes()
    ts = str(int(time.time() * 1000))
    digest = hmac.new(b"k", body + ts.encode(), hashlib.sha256).hexdigest()
    return {"x-retell-signature": f"v={ts},d={digest}"}, body


def test_tool_round_trip_parity_vapi() -> None:
    body = (VAPI_FX / "webhook_tool_calls.json").read_bytes()
    client = VoiceClient("vapi", "k", webhook_secret="s")
    ev = client.parse_webhook({"X-Vapi-Secret": "s"}, body)
    assert isinstance(ev, ToolCall) and ev.name
    reply = client.tool_response(ev, {"ok": True})
    assert reply["results"][0]["toolCallId"] == ev.tool_call_id


def test_tool_round_trip_parity_retell() -> None:
    client = VoiceClient("retell", "k")
    ev = client.parse_webhook(*_retell_signed_tool_request())
    assert isinstance(ev, ToolCall) and ev.name == "book_appointment"
    assert client.tool_response(ev, {"ok": True}) == {"ok": True}
