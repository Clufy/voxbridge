"""Pure mapping functions between voxbridge domain models and Vapi's wire format.

No I/O happens here — these are plain data transforms so they are trivially
unit-testable. Task 8 wires these into VapiProvider's HTTP calls.
"""

from __future__ import annotations

import copy
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
from ..models import Agent, Call, Tool
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
    if model.startswith("gemini"):
        return "google"
    return "openai"


def _vapi_tool(tool: Tool, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Map one Tool to Vapi's function-tool shape.

    With `existing` (the matching tool already on the assistant), only the
    fields voxbridge models are overlaid onto a copy of it, so per-tool
    settings such as ``async``, ``server.secret`` and ``server.headers`` survive.
    """
    entry: dict[str, Any] = (
        copy.deepcopy(existing) if existing is not None else {"type": "function"}
    )
    entry["function"] = {
        **(entry.get("function") or {}),
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }
    server = dict(entry.get("server") or {})
    if tool.endpoint_url is not None:
        server["url"] = tool.endpoint_url
    else:
        server.pop("url", None)
    if server:
        entry["server"] = server
    else:
        entry.pop("server", None)
    return entry


def _merge_vapi_tools(existing: list[dict[str, Any]], agent: Agent) -> list[dict[str, Any]]:
    """Non-function tools kept; function tools rebuilt in agent.tools order.

    A function tool matching an existing one by name keeps its provider-only
    settings; existing function tools absent from agent.tools are dropped.
    """
    kept: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for entry in existing:
        if entry.get("type") != "function":
            kept.append(entry)
            continue
        name = (entry.get("function") or {}).get("name")
        if isinstance(name, str):
            by_name.setdefault(name, entry)
    return kept + [_vapi_tool(tool, by_name.get(tool.name)) for tool in agent.tools]


def agent_to_vapi(agent: Agent) -> dict[str, Any]:
    """Map a voxbridge Agent to Vapi's CreateAssistantDTO shape."""
    model: dict[str, Any] = {
        "provider": _model_provider(agent.model),
        "model": agent.model,
        "messages": [{"role": "system", "content": agent.system_prompt}],
    }
    if agent.tools:
        model["tools"] = [_vapi_tool(tool) for tool in agent.tools]
    out: dict[str, Any] = {
        "name": agent.name,
        "model": model,
        "voice": _voice(agent.voice),
    }
    if agent.first_message is not None:
        out["firstMessage"] = agent.first_message
    return out


def merge_vapi_update(existing: dict[str, Any], agent: Agent) -> dict[str, Any]:
    """Build a PATCH body that overlays `agent` on the `existing` assistant.

    Keeps model/voice settings voxbridge does not model (temperature, non-function
    tools, per-tool server settings; voice settings while the voice provider is
    unchanged). Does not mutate `existing`.
    """
    model = copy.deepcopy(existing.get("model") or {})
    # A provider set on the assistant (e.g. "groq") is kept while the model is
    # unchanged; prefix inference only applies to a new model.
    if not (model.get("provider") and model.get("model") == agent.model):
        model["provider"] = _model_provider(agent.model)
    model["model"] = agent.model
    messages = model.get("messages") or []
    system = {"role": "system", "content": agent.system_prompt}
    for i, message in enumerate(messages):
        if message.get("role") == "system":
            messages[i] = system
            break
    else:
        messages.insert(0, system)
    model["messages"] = messages
    if agent.tools:
        model["tools"] = _merge_vapi_tools(model.get("tools") or [], agent)

    # Other voice settings belong to the TTS provider; keep them only while it
    # stays the same.
    voice = _voice(agent.voice)
    existing_voice = existing.get("voice") or {}
    if existing_voice.get("provider") == voice["provider"]:
        voice = {**copy.deepcopy(existing_voice), **voice}

    out: dict[str, Any] = {"name": agent.name, "model": model, "voice": voice}
    if agent.first_message is not None:
        out["firstMessage"] = agent.first_message
    return out


def vapi_to_agent(data: dict[str, Any]) -> Agent:
    """Map a Vapi Assistant payload to a voxbridge Agent, preserving raw."""
    model_block = data.get("model") or {}
    messages = model_block.get("messages") or []
    system_prompt = ""
    for message in messages:
        if message.get("role") == "system":
            system_prompt = message.get("content", "")
            break

    voice_block = data.get("voice") or {}
    voice_provider = voice_block.get("provider", "")
    voice_id = voice_block.get("voiceId", "")
    voice = f"{voice_provider}:{voice_id}"

    tools = [
        Tool(
            name=fn.get("name", ""),
            description=fn.get("description") or "",
            parameters=fn.get("parameters") or {},
            endpoint_url=(entry.get("server") or {}).get("url"),
        )
        for entry in model_block.get("tools") or []
        if entry.get("type") == "function"
        for fn in [entry.get("function") or {}]
    ]

    return Agent(
        id=data.get("id"),
        name=data.get("name", ""),
        first_message=data.get("firstMessage"),
        model=model_block.get("model", ""),
        system_prompt=system_prompt,
        voice=voice,
        tools=tools,
        raw=data,
    )


def vapi_to_call(data: dict[str, Any]) -> Call:
    """Map a Vapi Call payload to a voxbridge Call, preserving raw."""
    customer = data.get("customer") or {}
    artifact = data.get("artifact") or {}
    return Call(
        id=data.get("id"),
        agent_id=data.get("assistantId"),
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


def _decode_args(value: Any) -> dict[str, Any]:
    """Arguments arrive as a dict or a JSON string; anything undecodable -> {}."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _first_tool_call(message: dict[str, Any]) -> dict[str, Any]:
    """Pull name/arguments/id from Vapi's tool-calls message.

    toolCallList items are {id, type, function: {name, arguments}} (arguments a
    dict or JSON string); a flat {id, name, arguments} item is also accepted.
    Falls back to toolWithToolCallList[].toolCall.function.
    """
    flat = message.get("toolCallList") or []
    if flat:
        item = flat[0]
        fn = item.get("function") or {}
        return {
            "id": item.get("id"),
            "name": fn.get("name") or item.get("name") or "",
            "arguments": _decode_args(fn.get("arguments") or item.get("arguments")),
        }
    nested = message.get("toolWithToolCallList") or []
    if nested:
        tc = nested[0].get("toolCall") or {}
        fn = tc.get("function") or {}
        return {
            "id": tc.get("id"),
            "name": fn.get("name") or "",
            "arguments": _decode_args(fn.get("arguments")),
        }
    return {"id": None, "name": "", "arguments": {}}


def vapi_tool_response(event: ToolCall, result: Any) -> dict[str, Any]:
    """Build the webhook reply for a tool call; Vapi needs a single-line string result."""
    text = result if isinstance(result, str) else json.dumps(result, separators=(",", ":"))
    text = text.replace("\r", " ").replace("\n", " ")
    return {"results": [{"toolCallId": event.tool_call_id, "result": text}]}


def find_phone_number_id(numbers: list[dict[str, Any]], e164: str) -> str | None:
    """Return the id of the phone number matching `e164`, skipping entries without a number."""
    for entry in numbers:
        if entry.get("number") == e164:
            return entry.get("id")
    return None


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
