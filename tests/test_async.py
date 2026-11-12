import json
import pathlib

import httpx
import pytest
import respx

from voxbridge import VoiceClient
from voxbridge.errors import ProviderError
from voxbridge.models import Agent
from voxbridge.providers.retell import RetellProvider
from voxbridge.providers.vapi import VapiProvider

VFX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
RFX = pathlib.Path(__file__).parent / "fixtures" / "retell"
ASSISTANT = json.loads((VFX / "assistant.json").read_text())
CALL = json.loads((VFX / "call.json").read_text())
PHONE_NUMBERS = json.loads((VFX / "phone_numbers.json").read_text())
RLLM = json.loads((RFX / "llm.json").read_text())
RAGENT = json.loads((RFX / "agent.json").read_text())
RCALL = json.loads((RFX / "call.json").read_text())


def _agent() -> Agent:
    return Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel")


@respx.mock
async def test_async_create_agent_matches_sync() -> None:
    respx.post("https://api.vapi.ai/assistant").mock(
        return_value=httpx.Response(201, json=ASSISTANT)
    )
    async with VoiceClient(provider="vapi", api_key="k") as c:
        a = await c.acreate_agent(_agent())
    assert a.id == ASSISTANT["id"]


@respx.mock
async def test_async_get_and_list_calls_vapi() -> None:
    respx.get(f"https://api.vapi.ai/call/{CALL['id']}").mock(
        return_value=httpx.Response(200, json=CALL)
    )
    respx.get("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(200, json=[CALL, CALL])
    )
    p = VapiProvider("k")
    assert (await p.aget_call(CALL["id"])).transcript == CALL["artifact"]["transcript"]
    assert len(await p.alist_calls()) == 2
    await p.aclose()


@respx.mock
async def test_async_update_and_delete_agent_vapi() -> None:
    respx.get("https://api.vapi.ai/assistant/a1").mock(
        return_value=httpx.Response(200, json=ASSISTANT)
    )
    respx.patch("https://api.vapi.ai/assistant/a1").mock(
        return_value=httpx.Response(200, json=ASSISTANT)
    )
    route = respx.delete("https://api.vapi.ai/assistant/a1").mock(
        return_value=httpx.Response(204)
    )
    p = VapiProvider("k")
    assert (await p.aupdate_agent("a1", _agent())).id == ASSISTANT["id"]
    await p.adelete_agent("a1")
    assert route.called
    await p.aclose()


@respx.mock
async def test_async_create_call_vapi() -> None:
    respx.post("https://api.vapi.ai/call").mock(return_value=httpx.Response(201, json=CALL))
    p = VapiProvider("k")
    c = await p.acreate_call("a1", "+15550000000")
    assert c.id == CALL["id"]
    await p.aclose()


@respx.mock
async def test_async_create_agent_retell_two_calls() -> None:
    respx.post("https://api.retellai.com/create-retell-llm").mock(
        return_value=httpx.Response(201, json=RLLM)
    )
    respx.post("https://api.retellai.com/create-agent").mock(
        return_value=httpx.Response(201, json=RAGENT)
    )
    p = RetellProvider("k")
    a = await p.acreate_agent(Agent(name="S", system_prompt="x", model="gpt-4.1", voice="v1"))
    assert a.id == RAGENT["agent_id"]
    await p.aclose()


@respx.mock
async def test_async_get_agent_and_call_retell() -> None:
    respx.get(f"https://api.retellai.com/get-agent/{RAGENT['agent_id']}").mock(
        return_value=httpx.Response(200, json=RAGENT)
    )
    respx.get(f"https://api.retellai.com/v2/get-call/{RCALL['call_id']}").mock(
        return_value=httpx.Response(200, json=RCALL)
    )
    respx.post("https://api.retellai.com/v3/list-calls").mock(
        return_value=httpx.Response(200, json=[RCALL])
    )
    p = RetellProvider("k")
    assert (await p.aget_agent(RAGENT["agent_id"])).id == RAGENT["agent_id"]
    assert (await p.aget_call(RCALL["call_id"])).id == RCALL["call_id"]
    assert len(await p.alist_calls()) == 1
    await p.aclose()


@respx.mock
async def test_async_update_and_create_call_retell() -> None:
    respx.patch("https://api.retellai.com/update-agent/a1").mock(
        return_value=httpx.Response(200, json=RAGENT)
    )
    respx.post("https://api.retellai.com/v2/create-phone-call").mock(
        return_value=httpx.Response(201, json=RCALL)
    )
    p = RetellProvider("k")
    assert (await p.aupdate_agent("a1", _agent())).id == RAGENT["agent_id"]
    assert (await p.acreate_call("a1", "+15550000000")).id == RCALL["call_id"]
    await p.aclose()


@respx.mock
async def test_async_delete_agent_retell() -> None:
    route = respx.delete("https://api.retellai.com/delete-agent/a1").mock(
        return_value=httpx.Response(204)
    )
    p = RetellProvider("k")
    await p.adelete_agent("a1")
    assert route.called
    await p.aclose()


@respx.mock
async def test_async_client_context_manager_retell() -> None:
    respx.get(f"https://api.retellai.com/v2/get-call/{RCALL['call_id']}").mock(
        return_value=httpx.Response(200, json=RCALL)
    )
    async with VoiceClient(provider="retell", api_key="k") as c:
        assert (await c.aget_call(RCALL["call_id"])).id == RCALL["call_id"]


def test_async_surface_mirrors_sync() -> None:
    for cls in (VapiProvider, RetellProvider):
        for m in ("create_agent", "update_agent", "get_agent", "delete_agent",
                  "create_call", "get_call", "list_calls"):
            assert hasattr(cls, m) and hasattr(cls, "a" + m)


@respx.mock
async def test_async_vapi_update_gets_then_patches_merged_body() -> None:
    existing = json.loads(json.dumps(ASSISTANT))
    existing["model"]["temperature"] = 0.3
    get_route = respx.get("https://api.vapi.ai/assistant/a1").mock(
        return_value=httpx.Response(200, json=existing)
    )
    patch_route = respx.patch("https://api.vapi.ai/assistant/a1").mock(
        return_value=httpx.Response(200, json=ASSISTANT)
    )
    p = VapiProvider("k")
    await p.aupdate_agent("a1", _agent())
    assert get_route.call_count == 1
    assert patch_route.call_count == 1
    assert json.loads(patch_route.calls.last.request.content)["model"]["temperature"] == 0.3
    await p.aclose()


@respx.mock
async def test_async_vapi_create_call_resolves_e164_and_unknown_raises() -> None:
    respx.get("https://api.vapi.ai/phone-number").mock(
        return_value=httpx.Response(200, json=PHONE_NUMBERS)
    )
    post = respx.post("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(201, json=CALL)
    )
    p = VapiProvider("k")
    await p.acreate_call("a1", "+15551230000", from_number="+15550000001")
    assert json.loads(post.calls.last.request.content)["phoneNumberId"] == "pn_sanitized000"
    with pytest.raises(ProviderError):
        await p.acreate_call("a1", "+15551230000", from_number="+19999999999")
    assert post.call_count == 1
    await p.aclose()


@respx.mock
async def test_async_vapi_list_calls_limit() -> None:
    route = respx.get("https://api.vapi.ai/call").mock(
        return_value=httpx.Response(200, json=[CALL])
    )
    p = VapiProvider("k")
    await p.alist_calls(limit=5)
    assert route.calls.last.request.url.params["limit"] == "5"
    await p.alist_calls()
    assert "limit" not in route.calls.last.request.url.params
    await p.aclose()
