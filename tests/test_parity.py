"""Cross-provider parity suite.

Proves that vapi and retell, though wired to completely different wire
formats, hand back the same *domain types* with the same fields populated
for the shared sync surface. Each parametrized case sets up provider-specific
respx routes via a small per-provider helper, then runs identical assertions
against the returned Agent/Call objects.
"""

import json
import pathlib
from collections.abc import Callable

import httpx
import pytest
import respx

from voxbridge.client import VoiceClient
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
        return_value=httpx.Response(200, json=[RETELL_CALL])
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
