import json
import pathlib
from typing import Any

from voxbridge.events import ToolCall
from voxbridge.models import Agent
from voxbridge.providers._vapi_map import (
    _model_provider,
    _voice,
    agent_to_vapi,
    call_request,
    find_phone_number_id,
    merge_vapi_update,
    parse_webhook,
    vapi_to_agent,
    vapi_to_call,
    vapi_tool_response,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
ASSISTANT = json.loads((FX / "assistant.json").read_text())
PHONE_NUMBERS = json.loads((FX / "phone_numbers.json").read_text())
TOOL_CALLS = json.loads((FX / "webhook_tool_calls.json").read_text())


def test_voice_parsing() -> None:
    assert _voice("elevenlabs:rachel") == {"provider": "11labs", "voiceId": "rachel"}


def test_voice_parsing_bare_string_defaults_to_11labs() -> None:
    assert _voice("rachel") == {"provider": "11labs", "voiceId": "rachel"}


def test_voice_parsing_passes_through_other_providers() -> None:
    assert _voice("openai:alloy") == {"provider": "openai", "voiceId": "alloy"}


def test_voice_parsing_keeps_11labs_token_as_is() -> None:
    assert _voice("11labs:rachel") == {"provider": "11labs", "voiceId": "rachel"}


def test_vapi_to_agent_finds_system_prompt_not_at_index_0() -> None:
    # System prompt must be located by role, not by position: a non-system
    # message may precede it. Guards against a naive messages[0] refactor.
    data = {
        "id": "a1",
        "name": "S",
        "model": {
            "model": "gpt-4o",
            "messages": [
                {"role": "assistant", "content": "ignore me"},
                {"role": "system", "content": "real prompt"},
            ],
        },
        "voice": {"provider": "11labs", "voiceId": "rachel"},
    }
    assert vapi_to_agent(data).system_prompt == "real prompt"


def test_voice_round_trips_through_vapi_and_back() -> None:
    spec = "elevenlabs:rachel"
    voice_dict = _voice(spec)
    data = {
        "id": "a1",
        "name": "S",
        "model": {
            "provider": "openai",
            "model": "gpt-4o",
            "messages": [{"role": "system", "content": "x"}],
        },
        "voice": voice_dict,
    }
    agent = vapi_to_agent(data)
    assert agent.voice == "11labs:rachel"


def test_agent_to_vapi_puts_prompt_in_messages() -> None:
    a = Agent(
        name="S",
        system_prompt="be nice",
        model="gpt-4o",
        voice="elevenlabs:rachel",
        first_message="hi",
    )
    out = agent_to_vapi(a)
    assert out["firstMessage"] == "hi"
    assert out["model"]["messages"][0] == {"role": "system", "content": "be nice"}
    assert out["model"]["provider"] == "openai"
    assert out["model"]["model"] == "gpt-4o"
    assert out["voice"] == {"provider": "11labs", "voiceId": "rachel"}


def test_agent_to_vapi_omits_first_message_when_none() -> None:
    a = Agent(name="S", system_prompt="be nice", model="gpt-4o", voice="elevenlabs:rachel")
    out = agent_to_vapi(a)
    assert "firstMessage" not in out


def test_agent_to_vapi_maps_claude_model_provider() -> None:
    a = Agent(
        name="S",
        system_prompt="be nice",
        model="claude-3-5-sonnet",
        voice="elevenlabs:rachel",
    )
    out = agent_to_vapi(a)
    assert out["model"]["provider"] == "anthropic"


def test_agent_to_vapi_defaults_unknown_model_provider_to_openai() -> None:
    a = Agent(name="S", system_prompt="be nice", model="some-custom-model", voice="rachel")
    out = agent_to_vapi(a)
    assert out["model"]["provider"] == "openai"


def test_vapi_to_agent_reads_prompt_and_preserves_raw() -> None:
    data = json.loads((FX / "assistant.json").read_text())
    a = vapi_to_agent(data)
    assert a.id == data["id"]
    assert a.name == data["name"]
    assert a.first_message == data["firstMessage"]
    assert a.model == data["model"]["model"]
    assert a.system_prompt  # extracted from model.messages
    assert a.system_prompt == data["model"]["messages"][0]["content"]
    assert a.voice == "11labs:rachel"
    assert a.raw == data


def test_vapi_to_agent_defaults_system_prompt_when_no_system_message() -> None:
    data = {
        "id": "a2",
        "name": "S",
        "model": {"provider": "openai", "model": "gpt-4o", "messages": []},
        "voice": {"provider": "11labs", "voiceId": "rachel"},
    }
    a = vapi_to_agent(data)
    assert a.system_prompt == ""


def test_vapi_to_agent_defaults_model_when_absent() -> None:
    # A payload with no model block must not KeyError.
    a = vapi_to_agent({"id": "a1", "name": "S",
                       "voice": {"provider": "11labs", "voiceId": "rachel"}})
    assert a.model == "" and a.id == "a1"


def test_vapi_to_call_reads_transcript_and_number() -> None:
    data = json.loads((FX / "call.json").read_text())
    c = vapi_to_call(data)
    assert c.id == data["id"]
    assert c.agent_id == data["assistantId"]
    assert c.status == data["status"]
    assert c.to_number == "+15550000000"
    assert c.from_number == data["phoneNumberId"]
    assert c.transcript == data["artifact"]["transcript"]
    assert c.raw == data


def test_vapi_to_call_handles_missing_optional_fields() -> None:
    data = {"id": "c1", "status": "queued"}
    c = vapi_to_call(data)
    assert c.id == "c1"
    assert c.to_number is None
    assert c.from_number is None
    assert c.transcript is None
    assert c.raw == data


def test_call_request_without_from_number() -> None:
    out = call_request("assistant_abc123", "+15550000000", None)
    assert out == {"assistantId": "assistant_abc123", "customer": {"number": "+15550000000"}}
    assert "phoneNumberId" not in out


def test_call_request_with_from_number() -> None:
    out = call_request("assistant_abc123", "+15550000000", "phone_sanitized000")
    assert out == {
        "assistantId": "assistant_abc123",
        "customer": {"number": "+15550000000"},
        "phoneNumberId": "phone_sanitized000",
    }


def test_tool_calls_nested_function_shape() -> None:
    ev = parse_webhook(TOOL_CALLS)
    assert isinstance(ev, ToolCall)
    assert ev.name == "get_weather"
    assert ev.arguments == {"location": "San Francisco", "unit": "celsius"}
    assert ev.tool_call_id == "toolcall_sanitized000"


def _tc(item: dict[str, Any]) -> ToolCall:
    msg = {"type": "tool-calls", "call": {"id": "c"}, "toolCallList": [item]}
    ev = parse_webhook({"message": msg})
    assert isinstance(ev, ToolCall)
    return ev


def test_tool_calls_nested_string_arguments_decoded() -> None:
    ev = _tc({"id": "t", "function": {"name": "n", "arguments": '{"a": 1}'}})
    assert ev.arguments == {"a": 1}


def test_tool_calls_flat_shape_still_supported() -> None:
    ev = _tc({"id": "t", "name": "n", "arguments": {"a": 1}})
    assert ev.name == "n" and ev.arguments == {"a": 1} and ev.tool_call_id == "t"


def test_tool_calls_null_function_does_not_crash() -> None:
    ev = _tc({"id": "t", "function": None})
    assert ev.name == "" and ev.arguments == {}


def test_vapi_to_agent_maps_function_tools_back() -> None:
    data = {**ASSISTANT, "model": {**ASSISTANT["model"], "tools": [
        {"type": "function", "function": {"name": "book", "description": "d",
         "parameters": {"type": "object"}}, "server": {"url": "https://x/t"}},
        {"type": "transferCall", "destinations": []}]}}
    a = vapi_to_agent(data)
    assert [t.name for t in a.tools] == ["book"] and a.tools[0].endpoint_url == "https://x/t"


def _existing() -> dict[str, Any]:
    return {"model": {"provider": "openai", "model": "gpt-4o", "temperature": 0.2,
            "messages": [{"role": "system", "content": "old"},
                         {"role": "assistant", "content": "hi"}],
            "tools": [{"type": "transferCall"}]},
            "voice": {"provider": "11labs", "voiceId": "old", "stability": 0.5},
            "firstMessage": "keep me"}


def test_merge_update_keeps_unmodelled_model_settings() -> None:
    existing = _existing()
    body = merge_vapi_update(existing, Agent(name="N", system_prompt="new", model="claude-sonnet-4",
                                             voice="openai:alloy"))
    assert body["model"]["temperature"] == 0.2
    assert body["model"]["provider"] == "anthropic"
    assert body["model"]["messages"][0] == {"role": "system", "content": "new"}
    assert body["model"]["messages"][1]["role"] == "assistant"
    assert body["model"]["tools"] == [{"type": "transferCall"}]
    assert body["voice"] == {"provider": "openai", "voiceId": "alloy", "stability": 0.5}
    assert "firstMessage" not in body
    assert existing["model"]["messages"][0]["content"] == "old"


def test_merge_update_replaces_function_tools_keeps_others() -> None:
    existing = _existing()
    existing["model"]["tools"] = [
        {"type": "transferCall"},
        {"type": "function", "function": {"name": "stale"}},
    ]
    from voxbridge.models import Tool

    agent = Agent(name="N", system_prompt="p", model="gpt-4o", voice="openai:alloy",
                  tools=[Tool(name="fresh", description="d", parameters={"type": "object"})],
                  first_message="hello")
    body = merge_vapi_update(existing, agent)
    tools = body["model"]["tools"]
    assert tools[0] == {"type": "transferCall"}
    assert [t["function"]["name"] for t in tools[1:]] == ["fresh"]
    assert body["firstMessage"] == "hello"


def test_merge_update_inserts_system_message_when_missing() -> None:
    existing = {"model": {"messages": [{"role": "assistant", "content": "hi"}]}}
    body = merge_vapi_update(existing, Agent(name="N", system_prompt="sys", model="gpt-4o",
                                             voice="openai:alloy"))
    assert body["model"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "hi"},
    ]


def test_model_provider_gemini() -> None:
    assert _model_provider("gemini-2.5-flash") == "google"


def test_vapi_tool_response_string_and_object() -> None:
    ev = ToolCall(name="n", tool_call_id="t1", provider="vapi")
    assert vapi_tool_response(ev, "line1\nline2") == {
        "results": [{"toolCallId": "t1", "result": "line1 line2"}]
    }
    assert vapi_tool_response(ev, {"ok": True})["results"][0]["result"] == '{"ok":true}'


def test_find_phone_number_id_skips_entries_without_number() -> None:
    assert find_phone_number_id(PHONE_NUMBERS, "+15550000001") == "pn_sanitized000"
    assert find_phone_number_id(PHONE_NUMBERS, "+19999999999") is None


def test_vapi_to_agent_null_tool_description_becomes_empty() -> None:
    data = json.loads(json.dumps(ASSISTANT))
    data["model"]["tools"] = [
        {"type": "function", "function": {"name": "f", "description": None, "parameters": {}}}
    ]
    assert vapi_to_agent(data).tools[0].description == ""
