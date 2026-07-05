from voxbridge.events import CallEnded, ToolCall, WebhookEvent


def test_call_ended_matches():
    e: WebhookEvent = CallEnded(
        call_id="c1", provider="vapi", transcript="hi", ended_reason="hangup", raw={}
    )
    match e:
        case CallEnded(call_id=cid, transcript=t):
            assert cid == "c1" and t == "hi"
        case _:
            raise AssertionError

def test_tool_call_fields():
    e = ToolCall(
        call_id="c1", provider="retell", name="book",
        arguments={"day": "mon"}, tool_call_id="t1", raw={},
    )
    assert e.name == "book" and e.arguments["day"] == "mon"
