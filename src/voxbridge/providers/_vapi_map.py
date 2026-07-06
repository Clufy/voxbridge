"""Pure mapping functions between voxbridge domain models and Vapi's wire format.

No I/O happens here — these are plain data transforms so they are trivially
unit-testable. Task 8 wires these into VapiProvider's HTTP calls.
"""

from __future__ import annotations

import json
from typing import Any

from ..events import (
    CallEnded,
    CallStarted,
    ErrorEvent,
    ToolCall,
    TranscriptChunk,
    WebhookEvent,
)
from ..models import Agent, Call
from ._common import normalize_role

_VOICE_PROVIDER_ALIASES = {"elevenlabs": "11labs"}


def _voice(spec: str) -> dict[str, Any]:
    """Parse a voxbridge voice spec ("provider:voiceId" or bare voiceId).

    "elevenlabs:rachel" -> {"provider": "11labs", "voiceId": "rachel"}
    "rachel" (no colon)  -> {"provider": "11labs", "voiceId": "rachel"}
    "openai:alloy"       -> {"provider": "openai", "voiceId": "alloy"}
    """
    if ":" in spec:
        provider, voice_id = spec.split(":", 1)
    else:
        provider, voice_id = "elevenlabs", spec
    provider = _VOICE_PROVIDER_ALIASES.get(provider, provider)
    return {"provider": provider, "voiceId": voice_id}


def _model_provider(model: str) -> str:
    """Default the model provider by prefix convention."""
    if model.startswith("gpt"):
        return "openai"
    if model.startswith("claude"):
        return "anthropic"
    return "openai"


def agent_to_vapi(agent: Agent) -> dict[str, Any]:
    """Map a voxbridge Agent to Vapi's CreateAssistantDTO shape."""
    out: dict[str, Any] = {
        "name": agent.name,
        "model": {
            "provider": _model_provider(agent.model),
            "model": agent.model,
            "messages": [{"role": "system", "content": agent.system_prompt}],
        },
        "voice": _voice(agent.voice),
    }
    if agent.first_message is not None:
        out["firstMessage"] = agent.first_message
    return out


def vapi_to_agent(data: dict[str, Any]) -> Agent:
    """Map a Vapi Assistant payload to a voxbridge Agent, preserving raw."""
    model_block = data.get("model", {})
    messages = model_block.get("messages", [])
    system_prompt = ""
    for message in messages:
        if message.get("role") == "system":
            system_prompt = message.get("content", "")
            break

    voice_block = data.get("voice", {})
    voice_provider = voice_block.get("provider", "")
    voice_id = voice_block.get("voiceId", "")
    voice = f"{voice_provider}:{voice_id}"

    return Agent(
        id=data.get("id"),
        name=data.get("name", ""),
        first_message=data.get("firstMessage"),
        model=model_block["model"],
        system_prompt=system_prompt,
        voice=voice,
        raw=data,
    )


def vapi_to_call(data: dict[str, Any]) -> Call:
    """Map a Vapi Call payload to a voxbridge Call, preserving raw."""
    customer = data.get("customer") or {}
    artifact = data.get("artifact") or {}
    return Call(
        id=data.get("id"),
        status=data.get("status"),
        to_number=customer.get("number"),
        from_number=data.get("phoneNumberId"),
        transcript=artifact.get("transcript"),
        raw=data,
    )


def call_request(agent_id: str, to_number: str, from_number: str | None) -> dict[str, Any]:
    """Build the CreateCallDTO body Vapi expects for initiating an outbound call."""
    out: dict[str, Any] = {
        "assistantId": agent_id,
        "customer": {"number": to_number},
    }
    if from_number is not None:
        out["phoneNumberId"] = from_number
    return out


def _first_tool_call(message: dict[str, Any]) -> dict[str, Any]:
    """Pull name/arguments/id from Vapi's tool-calls message.

    Prefers the flat toolCallList shape ({id, name, arguments}); falls back to
    the OpenAI-style toolWithToolCallList[].toolCall.function shape where
    arguments is a JSON string.
    """
    flat = message.get("toolCallList") or []
    if flat:
        item = flat[0]
        return {
            "id": item.get("id"),
            "name": item.get("name", ""),
            "arguments": item.get("arguments") or {},
        }
    nested = message.get("toolWithToolCallList") or []
    if nested:
        tc = nested[0].get("toolCall", {})
        fn = tc.get("function", {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        return {"id": tc.get("id"), "name": fn.get("name", ""), "arguments": args or {}}
    return {"id": None, "name": "", "arguments": {}}


def parse_webhook(payload: dict[str, Any]) -> WebhookEvent:
    """Normalize a Vapi server-message payload into a WebhookEvent.

    Envelope is {"message": {"type": ...}}; the call id is at message.call.id.
    """
    # `or {}` (not the two-arg .get default) so an explicit JSON null coalesces
    # to {} the same as an absent key — providers emit nullable fields as null.
    message = payload.get("message") or {}
    mtype = message.get("type")
    call_id = (message.get("call") or {}).get("id")
    common: dict[str, Any] = {"call_id": call_id, "provider": "vapi", "raw": payload}

    if mtype == "status-update":
        status = message.get("status")
        if status == "ended":
            return CallEnded(ended_reason=message.get("endedReason"), **common)
        return CallStarted(**common)
    if mtype == "end-of-call-report":
        return CallEnded(
            transcript=(message.get("artifact") or {}).get("transcript"),
            ended_reason=message.get("endedReason"),
            **common,
        )
    if mtype == "transcript":
        return TranscriptChunk(
            role=normalize_role(message.get("role")),
            text=message.get("transcript") or "",
            **common,
        )
    if mtype == "tool-calls":
        tc = _first_tool_call(message)
        return ToolCall(
            name=tc["name"], arguments=tc["arguments"], tool_call_id=tc["id"], **common
        )
    return ErrorEvent(message=f"unhandled vapi message type: {mtype}", **common)
