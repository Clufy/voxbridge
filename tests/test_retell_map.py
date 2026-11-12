import json
import pathlib

import pytest

from voxbridge.models import Agent, Tool
from voxbridge.providers._retell_map import (
    agent_to_llm,
    agent_to_retell,
    llm_id_of,
    llm_update_body,
    phone_call_request,
    retell_call_items,
    retell_to_agent,
    retell_to_call,
    voice_from_retell,
    voice_to_retell,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "retell"
AGENT = json.loads((FX / "agent.json").read_text())
LLM = json.loads((FX / "llm.json").read_text())
CALL = json.loads((FX / "call.json").read_text())
LIST_V3 = json.loads((FX / "list_calls_v3.json").read_text())


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
    assert a.voice == "11labs:Rachel"
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
    assert a.voice == "11labs:Rachel"
    assert a.system_prompt == llm_data["general_prompt"]
    assert a.first_message == llm_data["begin_message"]
    assert a.model == llm_data["model"]
    assert a.raw == {**agent_data, "retell_llm": llm_data}


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
    assert c.agent_id == data["agent_id"]
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


@pytest.mark.parametrize(
    "spec",
    [
        "elevenlabs:Adrian",
        "11labs:Adrian",
        "cartesia:Cimo",
        "Rachel",
        "custom_voice_abc",
        "11labs:Adrian-v2",
    ],
)
def test_voice_round_trip_is_stable(spec: str) -> None:
    once = voice_to_retell(spec)
    assert voice_to_retell(voice_from_retell(once)) == once


def test_voice_to_retell_examples() -> None:
    assert voice_to_retell("elevenlabs:Adrian") == "11labs-Adrian"
    assert voice_to_retell("cartesia:Cimo") == "cartesia-Cimo"
    assert voice_to_retell("Rachel") == "Rachel"
    assert voice_to_retell("11labs:Adrian-v2") == "11labs-Adrian-v2"


def test_voice_from_retell_examples() -> None:
    assert voice_from_retell("retell-Cimo") == "retell:Cimo"
    assert voice_from_retell("11labs-Adrian-v2") == "11labs:Adrian-v2"
    assert voice_from_retell("custom_voice_abc") == "custom_voice_abc"
    assert voice_from_retell("a:b-c") == "a:b-c"


def test_agent_to_retell_uses_voice_to_retell() -> None:
    a = Agent(name="S", system_prompt="p", model="m", voice="elevenlabs:Adrian")
    assert agent_to_retell(a, "llm_1")["voice_id"] == "11labs-Adrian"


def test_retell_to_agent_with_llm_keeps_llm_in_raw() -> None:
    a = retell_to_agent(AGENT, LLM)
    assert a.system_prompt == LLM["general_prompt"] and a.raw["retell_llm"] == LLM
    assert a.raw["agent_id"] == AGENT["agent_id"] and a.voice == "11labs:Rachel"


def test_retell_to_agent_without_llm_raw_is_agent_data() -> None:
    assert retell_to_agent(AGENT).raw == AGENT


def test_model_prefers_model_config_primary() -> None:
    assert retell_to_agent(AGENT, {**LLM, "model_config": {"primary": "gpt-5"}}).model == "gpt-5"
    assert retell_to_agent(AGENT, {**LLM, "model_config": None}).model == LLM["model"]


def test_custom_tools_map_back_others_ignored() -> None:
    llm = {
        **LLM,
        "general_tools": [
            {"type": "custom", "name": "book", "description": None, "parameters": None,
             "url": "https://x.test/book"},
            {"type": "end_call", "name": "end_call"},
        ],
    }
    a = retell_to_agent(AGENT, llm)
    assert a.tools == [
        Tool(name="book", description="", parameters={}, endpoint_url="https://x.test/book")
    ]


def test_llm_id_of_handles_missing_null_and_other_engines() -> None:
    assert llm_id_of(AGENT) == "llm_sanitized000"
    assert llm_id_of({**AGENT, "response_engine": None}) is None
    custom = {"type": "custom-llm", "llm_websocket_url": "wss://x"}
    assert llm_id_of({**AGENT, "response_engine": custom}) is None
    assert llm_id_of({}) is None


def test_llm_update_body_leaves_unset_fields_out() -> None:
    a = Agent(name="S", system_prompt="p", model="m", voice="v")
    assert llm_update_body(a, LLM) == {"general_prompt": "p", "model": "m"}


def test_llm_update_body_keeps_builtin_tools() -> None:
    existing = {
        "general_tools": [
            {"type": "end_call", "name": "end_call"},
            {"type": "custom", "name": "old", "url": "https://old.test"},
        ]
    }
    a = Agent(
        name="S", system_prompt="p", model="m", voice="v", first_message="hi",
        tools=[Tool(name="new", description="d", parameters={}, endpoint_url="https://new.test")],
    )
    out = llm_update_body(a, existing)
    assert out["begin_message"] == "hi"
    assert out["general_tools"] == [
        {"type": "end_call", "name": "end_call"},
        {"type": "custom", "name": "new", "description": "d", "parameters": {}, "url": "https://new.test"},
    ]
    assert llm_update_body(a, {"general_tools": None})["general_tools"][0]["name"] == "new"


def test_retell_call_items_v3_and_bare() -> None:
    assert retell_call_items(LIST_V3) == LIST_V3["items"]
    assert retell_call_items([CALL]) == [CALL]
    assert retell_call_items({"items": None}) == []
    assert retell_call_items({}) == []


def test_retell_call_items_non_dict_non_list_is_empty() -> None:
    assert retell_call_items(None) == []
    assert retell_call_items("x") == []
