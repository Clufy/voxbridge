import json
import pathlib

import httpx
import pytest
import respx

from voxbridge.errors import ProviderError
from voxbridge.events import ToolCall
from voxbridge.models import Agent
from voxbridge.providers.vapi import VapiProvider

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
ASSISTANT = json.loads((FX / "assistant.json").read_text())
CALL = json.loads((FX / "call.json").read_text())
PHONE_NUMBERS = json.loads((FX / "phone_numbers.json").read_text())


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
    respx.get("https://api.vapi.ai/assistant/assistant_abc123").mock(
        return_value=httpx.Response(200, json=ASSISTANT)
    )
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


def _agent() -> Agent:
    return Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel")


@respx.mock
def test_update_agent_gets_then_patches_merged_body() -> None:
    existing = json.loads(json.dumps(ASSISTANT))
    existing["model"]["temperature"] = 0.3
    get_route = respx.get("https://api.vapi.ai/assistant/assistant_abc123").mock(
        return_value=httpx.Response(200, json=existing)
    )
    patch_route = respx.patch("https://api.vapi.ai/assistant/assistant_abc123").mock(
        return_value=httpx.Response(200, json=ASSISTANT)
    )
    p = VapiProvider("k")
    p.update_agent("assistant_abc123", _agent())
    assert get_route.call_count == 1
    assert patch_route.call_count == 1
    body = json.loads(patch_route.calls.last.request.content)
    assert body["model"]["temperature"] == 0.3
    p.close()


@respx.mock
def test_create_call_resolves_e164_from_number() -> None:
    respx.get("https://api.vapi.ai/phone-number").mock(
        return_value=httpx.Response(200, json=PHONE_NUMBERS)
    )
    post = respx.post("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(201, json=CALL)
    )
    p = VapiProvider("k")
    p.create_call("a1", "+15551230000", from_number="+15550000001")
    assert json.loads(post.calls.last.request.content)["phoneNumberId"] == "pn_sanitized000"
    p.close()


@respx.mock
def test_create_call_unknown_e164_raises_provider_error() -> None:
    respx.get("https://api.vapi.ai/phone-number").mock(
        return_value=httpx.Response(200, json=PHONE_NUMBERS)
    )
    post = respx.post("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(201, json=CALL)
    )
    p = VapiProvider("k")
    with pytest.raises(ProviderError, match="no Vapi phone number matches"):
        p.create_call("a1", "+15551230000", from_number="+19999999999")
    assert not post.called
    p.close()


@respx.mock
def test_create_call_id_from_number_passes_through_without_lookup() -> None:
    lookup = respx.get("https://api.vapi.ai/phone-number").mock(
        return_value=httpx.Response(200, json=PHONE_NUMBERS)
    )
    post = respx.post("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(201, json=CALL)
    )
    p = VapiProvider("k")
    p.create_call("a1", "+15551230000", from_number="pn_direct")
    assert lookup.call_count == 0
    assert json.loads(post.calls.last.request.content)["phoneNumberId"] == "pn_direct"
    p.close()


@respx.mock
def test_list_calls_limit_sent_as_query() -> None:
    route = respx.get("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(200, json=[CALL])
    )
    p = VapiProvider("k")
    p.list_calls(limit=5)
    assert route.calls.last.request.url.params["limit"] == "5"
    p.close()


@respx.mock
def test_list_calls_no_limit_sends_no_param() -> None:
    route = respx.get("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(200, json=[CALL])
    )
    p = VapiProvider("k")
    p.list_calls()
    assert "limit" not in route.calls.last.request.url.params
    p.close()


def test_vapi_timeout_forwarded() -> None:
    p = VapiProvider("k", timeout=5)
    assert p._http._client().timeout == httpx.Timeout(5)
    p.close()


def test_tool_response_delegates() -> None:
    ev = ToolCall(name="n", tool_call_id="t1", provider="vapi")
    assert VapiProvider("k").tool_response(ev, "ok") == {
        "results": [{"toolCallId": "t1", "result": "ok"}]
    }
