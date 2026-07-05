import json
import pathlib

from voxbridge.models import Agent
from voxbridge.providers._vapi_map import (
    _voice,
    agent_to_vapi,
    call_request,
    vapi_to_agent,
    vapi_to_call,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"


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


def test_vapi_to_call_reads_transcript_and_number() -> None:
    data = json.loads((FX / "call.json").read_text())
    c = vapi_to_call(data)
    assert c.id == data["id"]
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
