from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Tool(BaseModel):
    """A function the voice agent can call during a conversation.

    Attributes:
        name: Function name the model uses to invoke the tool.
        description: What the tool does, shown to the model.
        parameters: JSON Schema describing the tool's arguments.
        endpoint_url: Server URL the provider calls when the tool is invoked, if any.
    """

    model_config = ConfigDict(extra="ignore")
    name: str
    description: str
    parameters: dict[str, Any]
    endpoint_url: str | None = None


class Agent(BaseModel):
    """A provider-neutral voice agent definition.

    Attributes:
        name: Display name of the agent.
        system_prompt: Instructions that define the agent's behaviour.
        model: LLM model identifier, for example ``gpt-4o``.
        voice: Voice identifier on the provider.
        first_message: What the agent says when a call connects, if anything.
        tools: Tools the agent may call.
        id: Provider-assigned agent id; ``None`` until the agent is created.
        raw: Unmodified provider payload this agent was built from.
    """

    model_config = ConfigDict(extra="ignore")
    name: str
    system_prompt: str
    model: str
    voice: str
    first_message: str | None = None
    tools: list[Tool] = Field(default_factory=list)
    id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Call(BaseModel):
    """A phone call placed through a provider.

    Attributes:
        id: Provider-assigned call id.
        agent_id: Id of the agent handling the call.
        status: Provider-reported call status, for example ``ended``.
        to_number: Number that was dialled, in E.164 format.
        from_number: Number the call came from, in E.164 format.
        transcript: Full transcript, once the provider has one.
        raw: Unmodified provider payload this call was built from.
    """

    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    agent_id: str | None = None
    status: str | None = None
    to_number: str | None = None
    from_number: str | None = None
    transcript: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
