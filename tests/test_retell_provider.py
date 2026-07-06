import json
import pathlib

import httpx
import respx

from voxbridge.models import Agent
from voxbridge.providers.retell import RetellProvider

FX = pathlib.Path(__file__).parent / "fixtures" / "retell"
LLM = json.loads((FX / "llm.json").read_text())
AGENT = json.loads((FX / "agent.json").read_text())
CALL = json.loads((FX / "call.json").read_text())


@respx.mock
def test_create_agent_makes_two_calls_and_carries_prompt_through() -> None:
    respx.post("https://api.retellai.com/create-retell-llm").mock(
        return_value=httpx.Response(201, json=LLM)
    )
    respx.post("https://api.retellai.com/create-agent").mock(
        return_value=httpx.Response(201, json=AGENT)
    )
    p = RetellProvider("k")
    a = p.create_agent(
        Agent(name="S", system_prompt="be nice", model="gpt-4.1", voice="11labs-Rachel")
    )
    assert a.id == AGENT["agent_id"]
    assert a.system_prompt == LLM["general_prompt"]
    assert a.first_message == LLM["begin_message"]
    assert a.model == LLM["model"]
    p.close()


@respx.mock
def test_update_agent() -> None:
    respx.patch("https://api.retellai.com/update-agent/agent_sanitized000").mock(
        return_value=httpx.Response(200, json=AGENT)
    )
    p = RetellProvider("k")
    a = p.update_agent(
        "agent_sanitized000",
        Agent(name="S", system_prompt="x", model="gpt-4.1", voice="11labs-Rachel"),
    )
    assert isinstance(a, Agent)
    assert a.id == AGENT["agent_id"]
    assert a.name == AGENT["agent_name"]
    p.close()


@respx.mock
def test_get_agent() -> None:
    respx.get("https://api.retellai.com/get-agent/agent_sanitized000").mock(
        return_value=httpx.Response(200, json=AGENT)
    )
    p = RetellProvider("k")
    a = p.get_agent("agent_sanitized000")
    assert a.id == AGENT["agent_id"]
    assert a.name == AGENT["agent_name"]
    p.close()


@respx.mock
def test_delete_agent() -> None:
    route = respx.delete("https://api.retellai.com/delete-agent/agent_sanitized000").mock(
        return_value=httpx.Response(204)
    )
    p = RetellProvider("k")
    p.delete_agent("agent_sanitized000")  # returns None; asserting the call was made
    assert route.called
    p.close()


@respx.mock
def test_create_call() -> None:
    respx.post("https://api.retellai.com/v2/create-phone-call").mock(
        return_value=httpx.Response(201, json=CALL)
    )
    p = RetellProvider("k")
    c = p.create_call("agent_sanitized000", "+15550000000", from_number="+15550000001")
    assert c.id == CALL["call_id"]
    assert c.to_number == "+15550000000"
    p.close()


@respx.mock
def test_get_call() -> None:
    respx.get("https://api.retellai.com/v2/get-call/call_sanitized000").mock(
        return_value=httpx.Response(200, json=CALL)
    )
    p = RetellProvider("k")
    c = p.get_call("call_sanitized000")
    assert c.id == CALL["call_id"]
    assert c.transcript == CALL["transcript"]
    p.close()


@respx.mock
def test_list_calls_unwraps_calls_key() -> None:
    respx.post("https://api.retellai.com/v3/list-calls").mock(
        return_value=httpx.Response(200, json={"calls": [CALL, CALL]})
    )
    p = RetellProvider("k")
    calls = p.list_calls()
    assert len(calls) == 2
    assert calls[0].id == CALL["call_id"]
    p.close()


@respx.mock
def test_list_calls_handles_bare_list_response() -> None:
    respx.post("https://api.retellai.com/v3/list-calls").mock(
        return_value=httpx.Response(200, json=[CALL, CALL])
    )
    p = RetellProvider("k")
    calls = p.list_calls()
    assert len(calls) == 2
    assert calls[0].id == CALL["call_id"]
    p.close()
