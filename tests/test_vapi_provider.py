import json
import pathlib

import httpx
import respx

from voxbridge.models import Agent
from voxbridge.providers.vapi import VapiProvider

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
ASSISTANT = json.loads((FX / "assistant.json").read_text())
CALL = json.loads((FX / "call.json").read_text())


@respx.mock
def test_create_agent() -> None:
    respx.post("https://api.vapi.ai/assistant").mock(
        return_value=httpx.Response(201, json=ASSISTANT)
    )
    p = VapiProvider("k")
    a = p.create_agent(
        Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel")
    )
    assert a.id == ASSISTANT["id"]
    p.close()


@respx.mock
def test_update_agent() -> None:
    respx.patch("https://api.vapi.ai/assistant/assistant_abc123").mock(
        return_value=httpx.Response(200, json=ASSISTANT)
    )
    p = VapiProvider("k")
    a = p.update_agent(
        "assistant_abc123",
        Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel"),
    )
    assert isinstance(a, Agent)
    assert a.id == ASSISTANT["id"]
    assert a.name == ASSISTANT["name"]
    p.close()


@respx.mock
def test_get_agent() -> None:
    respx.get("https://api.vapi.ai/assistant/assistant_abc123").mock(
        return_value=httpx.Response(200, json=ASSISTANT)
    )
    p = VapiProvider("k")
    a = p.get_agent("assistant_abc123")
    assert a.id == ASSISTANT["id"]
    assert a.name == ASSISTANT["name"]
    p.close()


@respx.mock
def test_delete_agent() -> None:
    route = respx.delete("https://api.vapi.ai/assistant/assistant_abc123").mock(
        return_value=httpx.Response(204)
    )
    p = VapiProvider("k")
    p.delete_agent("assistant_abc123")  # returns None; asserting the call was made
    assert route.called
    p.close()


@respx.mock
def test_create_call() -> None:
    respx.post("https://api.vapi.ai/call").mock(return_value=httpx.Response(201, json=CALL))
    p = VapiProvider("k")
    c = p.create_call("assistant_abc123", "+15550000000")
    assert c.id == CALL["id"]
    assert c.to_number == "+15550000000"
    p.close()


@respx.mock
def test_get_call() -> None:
    respx.get("https://api.vapi.ai/call/call_def456").mock(
        return_value=httpx.Response(200, json=CALL)
    )
    p = VapiProvider("k")
    c = p.get_call("call_def456")
    assert c.id == CALL["id"]
    assert c.transcript == CALL["artifact"]["transcript"]
    p.close()


@respx.mock
def test_list_calls() -> None:
    respx.get("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(200, json=[CALL, CALL])
    )
    p = VapiProvider("k")
    calls = p.list_calls()
    assert len(calls) == 2
    assert calls[0].id == CALL["id"]
    p.close()
