from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Tool(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    description: str
    parameters: dict[str, Any]
    endpoint_url: str | None = None


class Agent(BaseModel):
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
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    agent_id: str | None = None
    status: str | None = None
    to_number: str | None = None
    from_number: str | None = None
    transcript: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
