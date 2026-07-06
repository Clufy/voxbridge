from voxbridge.models import Agent, Tool
from voxbridge.providers._retell_map import agent_to_llm
from voxbridge.providers._vapi_map import agent_to_vapi

TOOL = Tool(
    name="book", description="book it", parameters={"type": "object"},
    endpoint_url="https://x/y",
)


def _agent(**kw):
    base = dict(name="S", system_prompt="x", model="gpt-4o", voice="v")
    base.update(kw)
    return Agent(**base)


def test_tool_registers_with_vapi():
    body = agent_to_vapi(_agent(tools=[TOOL]))
    fn = body["model"]["tools"][0]
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "book"
    assert fn["function"]["description"] == "book it"
    assert fn["function"]["parameters"] == {"type": "object"}
    assert fn["server"]["url"] == "https://x/y"


def test_tool_registers_with_retell():
    body = agent_to_llm(_agent(model="gpt-4.1", tools=[TOOL]))
    tool = body["general_tools"][0]
    assert tool["type"] == "custom"
    assert tool["name"] == "book"
    assert tool["description"] == "book it"
    assert tool["url"] == "https://x/y"
    assert tool["parameters"] == {"type": "object"}


def test_no_tools_omits_key_on_both():
    # An agent with no tools must not emit an empty tools array.
    assert "tools" not in agent_to_vapi(_agent())["model"]
    assert "general_tools" not in agent_to_llm(_agent())


def test_tool_without_endpoint_url_omits_server():
    # Vapi: no endpoint_url → no server block (tool still registers).
    no_url = Tool(name="calc", description="d", parameters={"type": "object"})
    fn = agent_to_vapi(_agent(tools=[no_url]))["model"]["tools"][0]
    assert "server" not in fn
    assert fn["function"]["name"] == "calc"
