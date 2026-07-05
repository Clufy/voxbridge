from voxbridge.models import Agent, Call, Tool


def test_agent_roundtrips_and_defaults():
    a = Agent(name="Scheduler", system_prompt="be helpful", model="gpt-4o", voice="elevenlabs:rachel")
    assert a.id is None and a.tools == [] and a.raw == {}
    dumped = a.model_dump()
    assert dumped["name"] == "Scheduler"


def test_tool_requires_schema():
    t = Tool(name="book", description="book it", parameters={"type": "object"},
             endpoint_url="https://x/y")
    assert t.parameters == {"type": "object"}


def test_raw_preserved():
    c = Call(id="c1", raw={"vendor_field": 1})
    assert c.raw["vendor_field"] == 1
