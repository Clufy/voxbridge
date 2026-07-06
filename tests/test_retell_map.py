import json
import pathlib

from voxbridge.models import Agent
from voxbridge.providers._retell_map import (
    agent_to_llm,
    agent_to_retell,
    phone_call_request,
    retell_to_agent,
    retell_to_call,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "retell"


def test_agent_to_llm_maps_prompt_and_greeting() -> None:
    a = Agent(
        name="S",
        system_prompt="be nice",
        model="gpt-4.1",
        voice="11labs-Rachel",
        first_message="hi",
    )
    out = agent_to_llm(a)
    assert out == {
        "general_prompt": "be nice",
        "begin_message": "hi",
        "model": "gpt-4.1",
    }


def test_agent_to_llm_omits_begin_message_when_none() -> None:
    a = Agent(name="S", system_prompt="be nice", model="gpt-4.1", voice="11labs-Rachel")
    out = agent_to_llm(a)
    assert "begin_message" not in out
    assert out["general_prompt"] == "be nice"
    assert out["model"] == "gpt-4.1"


def test_agent_to_retell_references_llm_id() -> None:
    a = Agent(name="S", system_prompt="be nice", model="gpt-4.1", voice="11labs-Rachel")
    out = agent_to_retell(a, "llm_abc123")
    assert out == {
        "response_engine": {"type": "retell-llm", "llm_id": "llm_abc123"},
        "voice_id": "11labs-Rachel",
        "agent_name": "S",
    }


def test_retell_to_agent_reads_name_and_voice_without_llm_data() -> None:
    data = json.loads((FX / "agent.json").read_text())
    a = retell_to_agent(data)
    assert a.id == data["agent_id"]
    assert a.name == data["agent_name"]
    assert a.voice == data["voice_id"]
    assert a.system_prompt == ""
    assert a.first_message is None
    assert a.model == ""
    assert a.raw == data


def test_retell_to_agent_reads_prompt_and_model_from_llm_data() -> None:
    agent_data = json.loads((FX / "agent.json").read_text())
    llm_data = json.loads((FX / "llm.json").read_text())
    a = retell_to_agent(agent_data, llm_data)
    assert a.id == agent_data["agent_id"]
    assert a.name == agent_data["agent_name"]
    assert a.voice == agent_data["voice_id"]
    assert a.system_prompt == llm_data["general_prompt"]
    assert a.first_message == llm_data["begin_message"]
    assert a.model == llm_data["model"]
    # raw preserves the untouched agent payload only, llm_data is not merged in
    assert a.raw == agent_data


def test_retell_to_agent_defaults_first_message_when_llm_data_has_none() -> None:
    agent_data = json.loads((FX / "agent.json").read_text())
    llm_data = {"general_prompt": "x", "model": "gpt-4.1"}
    a = retell_to_agent(agent_data, llm_data)
    assert a.first_message is None
    assert a.system_prompt == "x"


def test_retell_to_call_extracts_transcript_numbers_and_status() -> None:
    data = json.loads((FX / "call.json").read_text())
    c = retell_to_call(data)
    assert c.id == data["call_id"]
    assert c.status == data["call_status"]
    assert c.to_number == data["to_number"]
    assert c.from_number == data["from_number"]
    assert c.transcript == data["transcript"]
    assert c.raw == data


def test_retell_to_call_handles_missing_optional_fields() -> None:
    data = {"call_id": "c1", "call_status": "registered"}
    c = retell_to_call(data)
    assert c.id == "c1"
    assert c.status == "registered"
    assert c.to_number is None
    assert c.from_number is None
    assert c.transcript is None
    assert c.raw == data


def test_phone_call_request_without_from_number() -> None:
    out = phone_call_request("agent_abc123", "+15550000000", None)
    assert out == {
        "to_number": "+15550000000",
        "override_agent_id": "agent_abc123",
    }
    assert "from_number" not in out


def test_phone_call_request_with_from_number() -> None:
    out = phone_call_request("agent_abc123", "+15550000000", "+15550000001")
    assert out == {
        "from_number": "+15550000001",
        "to_number": "+15550000000",
        "override_agent_id": "agent_abc123",
    }
