"""Pure mapping functions between voxbridge domain models and Retell's wire format.

No I/O happens here — these are plain data transforms so they are trivially
unit-testable. Task 10 wires these into RetellProvider's HTTP calls.

Retell splits an agent's prompt/greeting onto a separate Retell LLM object
(created via POST /create-retell-llm) referenced by the agent's
`response_engine.llm_id`; the agent object itself only carries name/voice.
"""

from __future__ import annotations

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


def voice_to_retell(spec: str) -> str:
    """Canonical "provider:Voice" spec -> Retell voice id ("provider-Voice")."""
    if ":" not in spec:
        return spec
    provider, rest = spec.split(":", 1)
    if provider == "elevenlabs":
        provider = "11labs"
    return f"{provider}-{rest}"


def voice_from_retell(voice_id: str) -> str:
    """Retell voice id -> canonical spec; ids with ":" or no "-" pass through."""
    if ":" in voice_id or "-" not in voice_id:
        return voice_id
    return voice_id.replace("-", ":", 1)


def llm_id_of(agent_data: dict[str, Any]) -> str | None:
    """The Retell LLM id of an agent, only for the retell-llm response engine."""
    engine = agent_data.get("response_engine") or {}
    if engine.get("type") != "retell-llm":
        return None
    llm_id = engine.get("llm_id")
    return llm_id if isinstance(llm_id, str) else None


def llm_update_body(agent: Agent, existing_llm: dict[str, Any]) -> dict[str, Any]:
    """Body for updating a Retell LLM; unset fields are left out, built-in tools kept."""
    out: dict[str, Any] = {"general_prompt": agent.system_prompt, "model": agent.model}
    if agent.first_message is not None:
        out["begin_message"] = agent.first_message
    if agent.tools:
        kept = [
            t for t in (existing_llm.get("general_tools") or []) if t.get("type") != "custom"
        ]
        out["general_tools"] = [*kept, *_retell_tools(agent)]
    return out


def retell_call_items(data: Any) -> list[dict[str, Any]]:
    """Call list from a v3 {"items": [...]} envelope or a bare array."""
    if isinstance(data, dict):
        items = data.get("items")
        return list(items) if items else []
    return list(data)


def retell_tool_response(event: ToolCall, result: Any) -> Any:
    """Retell custom functions take the result as the HTTP response body."""
    return result


def _retell_tools(agent: Agent) -> list[dict[str, Any]]:
    """Map Agent.tools to Retell's general_tools (type "custom") shape."""
    tools: list[dict[str, Any]] = []
    for tool in agent.tools:
        entry: dict[str, Any] = {
            "type": "custom",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        if tool.endpoint_url is not None:
            entry["url"] = tool.endpoint_url
        tools.append(entry)
    return tools


def agent_to_llm(agent: Agent) -> dict[str, Any]:
    """Map a voxbridge Agent to the body of Retell's CreateRetellLlmDTO."""
    out: dict[str, Any] = {
        "general_prompt": agent.system_prompt,
        "model": agent.model,
    }
    if agent.first_message is not None:
        out["begin_message"] = agent.first_message
    if agent.tools:
        out["general_tools"] = _retell_tools(agent)
    return out


def agent_to_retell(agent: Agent, llm_id: str) -> dict[str, Any]:
    """Map a voxbridge Agent to Retell's CreateAgentDTO shape, given an llm_id."""
    return {
        "response_engine": {"type": "retell-llm", "llm_id": llm_id},
        "voice_id": voice_to_retell(agent.voice),
        "agent_name": agent.name,
    }


def retell_to_agent(
    agent_data: dict[str, Any], llm_data: dict[str, Any] | None = None
) -> Agent:
    """Map a Retell Agent payload (plus optional Retell LLM payload) to an Agent.

    The Retell agent object does not carry the prompt, greeting, or model —
    those live on the separate Retell LLM object. When llm_data is not
    provided (e.g. a single GET /get-agent/{id}), system_prompt/model default
    to "" and first_message defaults to None. The raw payload preserved is
    the untouched agent_data only; llm_data is not merged into raw.
    """
    system_prompt = ""
    first_message = None
    model = ""
    tools: list[Tool] = []
    if llm_data is not None:
        system_prompt = llm_data.get("general_prompt") or ""
        first_message = llm_data.get("begin_message")
        model = (llm_data.get("model_config") or {}).get("primary") or llm_data.get("model") or ""
        for x in llm_data.get("general_tools") or []:
            if x.get("type") == "custom":
                tools.append(
                    Tool(
                        name=x.get("name") or "",
                        description=x.get("description") or "",
                        parameters=x.get("parameters") or {},
                        endpoint_url=x.get("url"),
                    )
                )

    return Agent(
        id=agent_data.get("agent_id"),
        name=agent_data.get("agent_name", ""),
        first_message=first_message,
        model=model,
        system_prompt=system_prompt,
        voice=voice_from_retell(agent_data.get("voice_id") or ""),
        tools=tools,
        raw=agent_data if llm_data is None else {**agent_data, "retell_llm": llm_data},
    )


def retell_to_call(data: dict[str, Any]) -> Call:
    """Map a Retell Call payload to a voxbridge Call, preserving raw."""
    return Call(
        id=data.get("call_id"),
        agent_id=data.get("agent_id"),
        status=data.get("call_status"),
        to_number=data.get("to_number"),
        from_number=data.get("from_number"),
        transcript=data.get("transcript"),
        raw=data,
    )


def phone_call_request(
    agent_id: str, to_number: str, from_number: str | None
) -> dict[str, Any]:
    """Build the CreatePhoneCallDTO body Retell expects for an outbound call.

    Retell routes the call to a specific agent via `override_agent_id`.
    `from_number` is required by Retell's API but kept optional here for
    signature parity with Vapi's `call_request`; it is omitted when None.
    """
    out: dict[str, Any] = {}
    if from_number is not None:
        out["from_number"] = from_number
    out["to_number"] = to_number
    out["override_agent_id"] = agent_id
    return out


def parse_webhook(payload: dict[str, Any]) -> WebhookEvent:
    """Normalize a Retell webhook payload into a WebhookEvent.

    Envelope is {"event": ..., "call": {...}}; the call id is at call.call_id.
    """
    event = payload.get("event")
    if event is None and "event" not in payload and "name" in payload and "args" in payload:
        return ToolCall(
            name=payload["name"],
            arguments=payload["args"] or {},
            tool_call_id=None,
            call_id=(payload.get("call") or {}).get("call_id"),
            provider="retell",
            raw=payload,
        )
    # `or {}` so a JSON null call coalesces the same as an absent key.
    call = payload.get("call") or {}
    common: dict[str, Any] = {
        "call_id": call.get("call_id"),
        "provider": "retell",
        "raw": payload,
    }

    if event == "call_started":
        return CallStarted(**common)
    if event in ("call_ended", "call_analyzed"):
        # call_ended and call_analyzed both fire for one call; both map to
        # CallEnded. Consumers dedupe on call_id (call_analyzed is the richer one).
        return CallEnded(
            transcript=call.get("transcript"),
            ended_reason=call.get("disconnection_reason"),
            **common,
        )
    if event == "transcript_updated":
        # Retell sends the full cumulative transcript each time; the newest turn
        # is the last transcript_object entry.
        turns = call.get("transcript_object") or []
        last = turns[-1] if turns else {}
        return TranscriptChunk(
            role=normalize_role(last.get("role")),
            text=last.get("content") or "",
            **common,
        )
    return ErrorEvent(message=f"unhandled retell event: {event}", **common)
