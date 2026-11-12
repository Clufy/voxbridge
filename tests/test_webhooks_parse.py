import hashlib
import hmac
import json
import pathlib

import pytest

from voxbridge.errors import SignatureError, VoxBridgeError
from voxbridge.events import CallEnded, CallStarted, ErrorEvent, ToolCall, TranscriptChunk
from voxbridge.providers._retell_map import parse_webhook as parse_retell
from voxbridge.providers._retell_map import retell_tool_response
from voxbridge.providers._vapi_map import parse_webhook as parse_vapi
from voxbridge.providers.retell import RetellProvider
from voxbridge.providers.vapi import VapiProvider

VFX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
RFX = pathlib.Path(__file__).parent / "fixtures" / "retell"

SECRET = "s3cr3t"


def _vapi_signed(name: str) -> tuple[dict[str, str], bytes]:
    body = (VFX / name).read_bytes()
    return {"X-Vapi-Secret": SECRET}, body


def _retell_signed(name: str) -> tuple[dict[str, str], bytes]:
    body = (RFX / name).read_bytes()
    ts = "1735689600000"
    digest = hmac.new(SECRET.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
    return {"x-retell-signature": f"v={ts},d={digest}"}, body


# --- Vapi ---------------------------------------------------------------


def test_vapi_call_ended():
    p = VapiProvider("k", webhook_secret=SECRET)
    ev = p.parse_webhook(*_vapi_signed("webhook_call_ended.json"))
    assert isinstance(ev, CallEnded)
    assert ev.call_id == "call_sanitized000"
    assert ev.provider == "vapi"
    assert ev.transcript.startswith("AI: Hello")
    assert ev.ended_reason == "customer-ended-call"


def test_vapi_transcript():
    p = VapiProvider("k", webhook_secret=SECRET)
    ev = p.parse_webhook(*_vapi_signed("webhook_transcript.json"))
    assert isinstance(ev, TranscriptChunk)
    assert ev.role == "user"
    assert ev.text == "what are your hours"


def test_vapi_tool_calls():
    p = VapiProvider("k", webhook_secret=SECRET)
    ev = p.parse_webhook(*_vapi_signed("webhook_tool_calls.json"))
    assert isinstance(ev, ToolCall)
    assert ev.name == "get_weather"
    assert ev.arguments == {"location": "San Francisco", "unit": "celsius"}
    assert ev.tool_call_id == "toolcall_sanitized000"


def test_vapi_tampered_body_rejected():
    headers, body = _vapi_signed("webhook_call_ended.json")
    p = VapiProvider("k", webhook_secret=SECRET)
    with pytest.raises(SignatureError):
        p.parse_webhook({"X-Vapi-Secret": "wrong"}, body)


def test_vapi_no_secret_skips_verification():
    _, body = _vapi_signed("webhook_call_ended.json")
    p = VapiProvider("k")  # no webhook_secret configured
    ev = p.parse_webhook({}, body)
    assert isinstance(ev, CallEnded)


# --- Retell -------------------------------------------------------------


def test_retell_call_started():
    p = RetellProvider("k", webhook_secret=SECRET)
    ev = p.parse_webhook(*_retell_signed("webhook_call_started.json"))
    assert isinstance(ev, CallStarted)
    assert ev.call_id == "call_sanitized000"
    assert ev.provider == "retell"


def test_retell_call_ended():
    p = RetellProvider("k", webhook_secret=SECRET)
    ev = p.parse_webhook(*_retell_signed("webhook_call_ended.json"))
    assert isinstance(ev, CallEnded)
    assert ev.transcript.startswith("Agent: Hi")
    assert ev.ended_reason == "user_hangup"


def test_retell_transcript():
    p = RetellProvider("k", webhook_secret=SECRET)
    ev = p.parse_webhook(*_retell_signed("webhook_transcript.json"))
    assert isinstance(ev, TranscriptChunk)
    assert ev.role == "user"
    assert ev.text == "I'd like to check my order status."


def test_retell_tampered_body_rejected():
    headers, body = _retell_signed("webhook_call_ended.json")
    p = RetellProvider("k", webhook_secret=SECRET)
    with pytest.raises(SignatureError):
        p.parse_webhook(headers, body + b"tampered")


# --- Cross-provider parity ---------------------------------------------


def test_both_providers_call_ended_same_shape():
    vp = VapiProvider("k", webhook_secret=SECRET)
    rp = RetellProvider("k", webhook_secret=SECRET)
    ev_v = vp.parse_webhook(*_vapi_signed("webhook_call_ended.json"))
    ev_r = rp.parse_webhook(*_retell_signed("webhook_call_ended.json"))
    assert type(ev_v) is type(ev_r) is CallEnded
    # Structural parity: derive the field set from the class, not an instance
    # (an instance keyset comparison is a tautology under extra="ignore").
    assert set(CallEnded.model_fields) == {
        "call_id", "provider", "raw", "transcript", "ended_reason"
    }
    # Value parity: both must correctly populate provider, the full raw
    # envelope, and the CallEnded-specific fields — not just carry the keys.
    assert ev_v.provider == "vapi" and ev_r.provider == "retell"
    assert ev_v.raw.get("message") is not None  # full Vapi envelope, not a sub-object
    assert ev_r.raw.get("event") == "call_ended"  # full Retell envelope
    assert ev_v.transcript and ev_v.ended_reason
    assert ev_r.transcript and ev_r.ended_reason


def test_transcript_missing_role_is_none():
    # A transcript message with no role at all → role None (not a crash).
    ev = parse_vapi({"message": {"type": "transcript", "transcript": "hi",
                                 "call": {"id": "c1"}}})
    assert isinstance(ev, TranscriptChunk) and ev.role is None


def test_both_providers_transcript_role_normalized():
    # Bot turn: Vapi says "assistant", Retell says "agent" — both normalize to
    # "assistant" so a consumer switching on role works across providers.
    ev_v = parse_vapi({"message": {"type": "transcript", "role": "assistant",
        "transcript": "hi", "call": {"id": "c1"}}})
    ev_r = parse_retell({"event": "transcript_updated", "call": {"call_id": "c1",
        "transcript_object": [{"role": "agent", "content": "hi"}]}})
    assert ev_v.role == ev_r.role == "assistant"


def test_verify_signature_delegates():
    headers, body = _retell_signed("webhook_call_started.json")
    p = RetellProvider("k", webhook_secret=SECRET)
    assert p.verify_signature(headers, body) is True
    assert p.verify_signature({"x-retell-signature": "v=1,d=bad"}, body) is False


# --- Synthetic branch coverage (pure parse functions) ------------------


def test_vapi_status_update_ringing_is_call_started():
    ev = parse_vapi({"message": {"type": "status-update", "status": "ringing",
                                 "call": {"id": "c1"}}})
    assert isinstance(ev, CallStarted)
    assert ev.call_id == "c1"


def test_vapi_status_update_ended_is_call_ended():
    ev = parse_vapi({"message": {"type": "status-update", "status": "ended",
                                 "endedReason": "hangup", "call": {"id": "c1"}}})
    assert isinstance(ev, CallEnded)
    assert ev.ended_reason == "hangup"


def test_vapi_tool_calls_nested_fallback_parses_json_string_args():
    # No toolCallList — force the toolWithToolCallList fallback with string args.
    ev = parse_vapi({"message": {"type": "tool-calls", "call": {"id": "c1"},
        "toolWithToolCallList": [{"toolCall": {"id": "t9",
            "function": {"name": "book", "arguments": '{"day": "mon"}'}}}]}})
    assert isinstance(ev, ToolCall)
    assert ev.name == "book"
    assert ev.arguments == {"day": "mon"}
    assert ev.tool_call_id == "t9"


def test_vapi_tool_calls_malformed_json_args_fall_back_to_empty():
    ev = parse_vapi({"message": {"type": "tool-calls", "call": {"id": "c1"},
        "toolWithToolCallList": [{"toolCall": {"id": "t9",
            "function": {"name": "book", "arguments": "not json"}}}]}})
    assert isinstance(ev, ToolCall)
    assert ev.arguments == {}


def test_vapi_tool_calls_empty_yields_blank_tool():
    # Neither array present — defensive fallback, no IndexError.
    ev = parse_vapi({"message": {"type": "tool-calls", "call": {"id": "c1"}}})
    assert isinstance(ev, ToolCall)
    assert ev.name == "" and ev.arguments == {} and ev.tool_call_id is None


def test_vapi_unknown_type_is_error_event():
    ev = parse_vapi({"message": {"type": "hang-notification", "call": {"id": "c1"}}})
    assert isinstance(ev, ErrorEvent)
    assert "hang-notification" in ev.message


def test_retell_unknown_event_is_error_event():
    ev = parse_retell({"event": "call_registered", "call": {"call_id": "c1"}})
    assert isinstance(ev, ErrorEvent)
    assert "call_registered" in ev.message


# --- Null-valued fields must coalesce, not crash (review #1,#2,#3,#7) ----


def test_vapi_null_message_and_call_do_not_crash():
    assert isinstance(parse_vapi({"message": None}), ErrorEvent)
    ev = parse_vapi({"message": {"type": "transcript", "role": "user",
                                 "transcript": "hi", "call": None}})
    assert isinstance(ev, TranscriptChunk) and ev.call_id is None


def test_vapi_null_artifact_yields_none_transcript():
    ev = parse_vapi({"message": {"type": "end-of-call-report", "endedReason": "x",
                                 "call": {"id": "c1"}, "artifact": None}})
    assert isinstance(ev, CallEnded)
    assert ev.transcript is None and ev.ended_reason == "x"


def test_retell_null_call_does_not_crash():
    ev = parse_retell({"event": "call_started", "call": None})
    assert isinstance(ev, CallStarted) and ev.call_id is None


def test_null_transcript_text_coalesces_to_empty_string():
    ev_v = parse_vapi({"message": {"type": "transcript", "role": "user",
                                   "transcript": None, "call": {"id": "c1"}}})
    assert isinstance(ev_v, TranscriptChunk) and ev_v.text == ""
    ev_r = parse_retell({"event": "transcript_updated", "call": {"call_id": "c1",
        "transcript_object": [{"role": "user", "content": None}]}})
    assert isinstance(ev_r, TranscriptChunk) and ev_r.text == ""


# --- Malformed bodies raise typed VoxBridgeError (review #5,#6) ----------


@pytest.mark.parametrize("provider_cls", [VapiProvider, RetellProvider])
@pytest.mark.parametrize("body", [b"", b"{not json", b"null", b"[]", b'"x"', b"42"])
def test_malformed_body_raises_voxbridge_error(provider_cls, body):
    p = provider_cls("k")  # no secret → verification skipped, reaches decode
    with pytest.raises(VoxBridgeError):
        p.parse_webhook({}, body)


# --- Retell replay window is reachable through the provider (review #8) --


def test_retell_max_age_rejects_stale_through_provider():
    # The 2025-01-01 signed fixture is well older than a 5-minute window.
    p = RetellProvider("k", webhook_secret=SECRET, webhook_max_age=300)
    with pytest.raises(SignatureError):
        p.parse_webhook(*_retell_signed("webhook_call_started.json"))
    # Same request with no window configured still parses.
    p2 = RetellProvider("k", webhook_secret=SECRET)
    assert isinstance(
        p2.parse_webhook(*_retell_signed("webhook_call_started.json")), CallStarted
    )


def test_client_forwards_max_age_to_retell():
    from voxbridge import VoiceClient

    c = VoiceClient("retell", "k", webhook_secret=SECRET, webhook_max_age=300)
    with pytest.raises(SignatureError):
        c.parse_webhook(*_retell_signed("webhook_call_started.json"))
    c.close()


def test_custom_function_parses_to_tool_call() -> None:
    payload = json.loads((RFX / "custom_function.json").read_text())
    ev = parse_retell(payload)
    assert isinstance(ev, ToolCall) and ev.name == "book_appointment"
    assert ev.arguments == {"day": "monday"} and ev.call_id == "call_sanitized000"
    assert ev.provider == "retell" and ev.tool_call_id is None and ev.raw == payload
    assert retell_tool_response(ev, {"ok": True}) == {"ok": True}


def test_custom_function_null_args_and_call() -> None:
    ev = parse_retell({"name": "x", "args": None, "call": None})
    assert isinstance(ev, ToolCall)
    assert ev.arguments == {} and ev.call_id is None


def test_payload_with_event_key_is_not_custom_function() -> None:
    assert isinstance(parse_retell({"event": "nope", "name": "x", "args": {}}), ErrorEvent)
