import hashlib
import hmac
import json
import pathlib
import time

import httpx
import pytest
import respx

from voxbridge.errors import NotSupported, ProviderError, SignatureError
from voxbridge.events import CallStarted, ToolCall
from voxbridge.models import Agent, Tool
from voxbridge.providers.retell import RetellProvider

FX = pathlib.Path(__file__).parent / "fixtures" / "retell"
LLM = json.loads((FX / "llm.json").read_text())
AGENT = json.loads((FX / "agent.json").read_text())
CALL = json.loads((FX / "call.json").read_text())
WEBHOOK_BODY = (FX / "webhook_call_started.json").read_bytes()

B = "https://api.retellai.com"


def _agent() -> Agent:
    return Agent(name="S", system_prompt="x", model="gpt-4.1", voice="v")


def _agent_routes() -> None:
    respx.get(f"{B}/get-agent/agent_sanitized000").mock(
        return_value=httpx.Response(200, json=AGENT)
    )
    respx.get(f"{B}/get-retell-llm/llm_sanitized000").mock(
        return_value=httpx.Response(200, json=LLM)
    )


@respx.mock
def test_create_agent_makes_two_calls_and_carries_prompt_through() -> None:
    respx.post(f"{B}/create-retell-llm").mock(return_value=httpx.Response(201, json=LLM))
    respx.post(f"{B}/create-agent").mock(return_value=httpx.Response(201, json=AGENT))
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
def test_get_agent_fetches_llm_and_carries_prompt() -> None:
    _agent_routes()
    p = RetellProvider("k")
    a = p.get_agent("agent_sanitized000")
    assert a.id == AGENT["agent_id"]
    assert a.name == AGENT["agent_name"]
    assert a.system_prompt == LLM["general_prompt"]
    assert a.first_message == LLM["begin_message"]
    assert a.model == LLM["model"]
    p.close()


@respx.mock
def test_get_agent_non_llm_engine_returns_agent_without_llm_fetch() -> None:
    data = {**AGENT, "response_engine": {"type": "custom-llm"}}
    respx.get(f"{B}/get-agent/agent_sanitized000").mock(
        return_value=httpx.Response(200, json=data)
    )
    llm_route = respx.get(f"{B}/get-retell-llm/llm_sanitized000").mock(
        return_value=httpx.Response(200, json=LLM)
    )
    p = RetellProvider("k")
    a = p.get_agent("agent_sanitized000")
    assert a.id == AGENT["agent_id"]
    assert a.system_prompt == ""
    assert llm_route.call_count == 0
    p.close()


@respx.mock
def test_update_agent_patches_llm_in_place_then_agent() -> None:
    _agent_routes()
    llm_patch = respx.patch(f"{B}/update-retell-llm/llm_sanitized000").mock(
        return_value=httpx.Response(200, json=LLM)
    )
    agent_patch = respx.patch(f"{B}/update-agent/agent_sanitized000").mock(
        return_value=httpx.Response(200, json=AGENT)
    )
    p = RetellProvider("k")
    a = p.update_agent(
        "agent_sanitized000",
        Agent(name="S", system_prompt="new prompt", model="gpt-4.1", voice="elevenlabs:Adrian"),
    )
    assert isinstance(a, Agent)
    assert a.id == AGENT["agent_id"]
    assert a.system_prompt == LLM["general_prompt"]
    assert json.loads(llm_patch.calls.last.request.content)["general_prompt"] == "new prompt"
    assert json.loads(agent_patch.calls.last.request.content)["voice_id"] == "11labs-Adrian"
    order = [(c.request.method, c.request.url.path) for c in respx.calls]
    assert order == [
        ("GET", "/get-agent/agent_sanitized000"),
        ("GET", "/get-retell-llm/llm_sanitized000"),
        ("PATCH", "/update-retell-llm/llm_sanitized000"),
        ("PATCH", "/update-agent/agent_sanitized000"),
    ]
    p.close()


@pytest.mark.parametrize(
    "engine", [None, "absent", {"type": "custom-llm"}], ids=["none", "absent", "custom"]
)
@respx.mock
def test_update_agent_without_retell_llm_engine_raises_not_supported(engine: object) -> None:
    data = {k: v for k, v in AGENT.items() if k != "response_engine"}
    if engine != "absent":
        data["response_engine"] = engine
    respx.get(f"{B}/get-agent/agent_sanitized000").mock(
        return_value=httpx.Response(200, json=data)
    )
    llm_patch = respx.patch(f"{B}/update-retell-llm/llm_sanitized000")
    agent_patch = respx.patch(f"{B}/update-agent/agent_sanitized000")
    p = RetellProvider("k")
    with pytest.raises(NotSupported, match="no retell-llm response engine"):
        p.update_agent("agent_sanitized000", _agent())
    assert llm_patch.call_count == 0
    assert agent_patch.call_count == 0
    p.close()


@respx.mock
def test_create_agent_rolls_back_llm_when_agent_create_fails() -> None:
    respx.post(f"{B}/create-retell-llm").mock(return_value=httpx.Response(201, json=LLM))
    respx.post(f"{B}/create-agent").mock(return_value=httpx.Response(400, json={"error": "bad"}))
    delete = respx.delete(f"{B}/delete-retell-llm/llm_sanitized000").mock(
        return_value=httpx.Response(204)
    )
    p = RetellProvider("k")
    with pytest.raises(ProviderError):
        p.create_agent(_agent())
    assert delete.call_count == 1
    p.close()


@respx.mock
def test_create_agent_rollback_failure_still_raises_original() -> None:
    respx.post(f"{B}/create-retell-llm").mock(return_value=httpx.Response(201, json=LLM))
    respx.post(f"{B}/create-agent").mock(return_value=httpx.Response(400, json={"error": "bad"}))
    delete = respx.delete(f"{B}/delete-retell-llm/llm_sanitized000").mock(
        return_value=httpx.Response(500)
    )
    p = RetellProvider("k")
    with pytest.raises(ProviderError) as exc:
        p.create_agent(_agent())
    assert exc.value.status_code == 400
    assert delete.called
    p.close()


@respx.mock
def test_delete_agent() -> None:
    route = respx.delete(f"{B}/delete-agent/agent_sanitized000").mock(
        return_value=httpx.Response(204)
    )
    p = RetellProvider("k")
    p.delete_agent("agent_sanitized000")  # returns None; asserting the call was made
    assert route.called
    p.close()


@respx.mock
def test_create_call() -> None:
    respx.post(f"{B}/v2/create-phone-call").mock(return_value=httpx.Response(201, json=CALL))
    p = RetellProvider("k")
    c = p.create_call("agent_sanitized000", "+15550000000", from_number="+15550000001")
    assert c.id == CALL["call_id"]
    assert c.to_number == "+15550000000"
    p.close()


@respx.mock
def test_create_call_without_from_number_raises_value_error() -> None:
    route = respx.post(f"{B}/v2/create-phone-call")
    p = RetellProvider("k")
    with pytest.raises(ValueError, match="Retell requires from_number"):
        p.create_call("agent_sanitized000", "+15550000000")
    assert route.call_count == 0
    p.close()


@respx.mock
def test_get_call() -> None:
    respx.get(f"{B}/v2/get-call/call_sanitized000").mock(
        return_value=httpx.Response(200, json=CALL)
    )
    p = RetellProvider("k")
    c = p.get_call("call_sanitized000")
    assert c.id == CALL["call_id"]
    assert c.transcript == CALL["transcript"]
    p.close()


@respx.mock
def test_list_calls_reads_v3_items_and_sends_limit() -> None:
    route = respx.post(f"{B}/v3/list-calls").mock(
        return_value=httpx.Response(200, json={"items": [CALL, CALL]})
    )
    p = RetellProvider("k")
    calls = p.list_calls(limit=5)
    assert len(calls) == 2
    assert calls[0].id == CALL["call_id"]
    assert json.loads(route.calls.last.request.content) == {"limit": 5}
    p.close()


@respx.mock
def test_list_calls_without_limit_sends_empty_body() -> None:
    route = respx.post(f"{B}/v3/list-calls").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    p = RetellProvider("k")
    assert p.list_calls() == []
    assert json.loads(route.calls.last.request.content) == {}
    p.close()


@respx.mock
def test_list_calls_handles_bare_list_response() -> None:
    respx.post(f"{B}/v3/list-calls").mock(return_value=httpx.Response(200, json=[CALL, CALL]))
    p = RetellProvider("k")
    calls = p.list_calls()
    assert len(calls) == 2
    assert calls[0].id == CALL["call_id"]
    p.close()


@respx.mock
def test_list_calls_retried_on_500() -> None:
    route = respx.post(f"{B}/v3/list-calls").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"items": [CALL]})]
    )
    p = RetellProvider("k")
    assert len(p.list_calls()) == 1
    assert route.call_count == 2
    p.close()


def _sign(body: bytes, secret: str, ts_ms: int) -> dict[str, str]:
    digest = hmac.new(secret.encode(), body + str(ts_ms).encode(), hashlib.sha256).hexdigest()
    return {"x-retell-signature": f"v={ts_ms},d={digest}"}


def test_unsigned_webhook_rejected_by_default() -> None:
    with pytest.raises(SignatureError):
        RetellProvider("k").parse_webhook({}, WEBHOOK_BODY)


def test_webhook_signed_with_api_key_accepted_by_default() -> None:
    headers = _sign(WEBHOOK_BODY, "k", int(time.time() * 1000))
    assert isinstance(RetellProvider("k").parse_webhook(headers, WEBHOOK_BODY), CallStarted)


def test_explicit_webhook_secret_overrides_api_key() -> None:
    headers = _sign(WEBHOOK_BODY, "k", int(time.time() * 1000))
    with pytest.raises(SignatureError):
        RetellProvider("k", webhook_secret="other").parse_webhook(headers, WEBHOOK_BODY)


def test_default_max_age_rejects_old_signature() -> None:
    headers = _sign(WEBHOOK_BODY, "k", int((time.time() - 600) * 1000))
    with pytest.raises(SignatureError):
        RetellProvider("k").parse_webhook(headers, WEBHOOK_BODY)


def test_max_age_none_disables_replay_check() -> None:
    headers = _sign(WEBHOOK_BODY, "k", int((time.time() - 600) * 1000))
    p = RetellProvider("k", webhook_max_age=None)
    assert isinstance(p.parse_webhook(headers, WEBHOOK_BODY), CallStarted)


def test_tool_response_returns_result_as_body() -> None:
    event = ToolCall(call_id="c", provider="retell", name="n")
    assert RetellProvider("k").tool_response(event, {"ok": True}) == {"ok": True}


def test_retell_timeout_forwarded() -> None:
    p = RetellProvider("k", timeout=5)
    assert p._http._client().timeout == httpx.Timeout(5)
    p.close()


# --- Retell custom tools need a url (final review #11) ----------------------


def _agent_with_urlless_tool() -> Agent:
    return _agent().model_copy(update={"tools": [
        Tool(name="ok", description="d", parameters={}, endpoint_url="https://x.test/ok"),
        Tool(name="lookup", description="d", parameters={}),
    ]})


@respx.mock
def test_create_agent_tool_without_endpoint_url_raises_before_request() -> None:
    p = RetellProvider("k")
    with pytest.raises(ValueError, match="Retell custom tools require endpoint_url: lookup"):
        p.create_agent(_agent_with_urlless_tool())
    assert len(respx.calls) == 0


@respx.mock
def test_update_agent_tool_without_endpoint_url_raises_before_request() -> None:
    p = RetellProvider("k")
    with pytest.raises(ValueError, match="Retell custom tools require endpoint_url: lookup"):
        p.update_agent("agent_sanitized000", _agent_with_urlless_tool())
    assert len(respx.calls) == 0
