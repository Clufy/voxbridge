from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")
    call_id: str | None = None
    provider: str
    raw: dict[str, Any] = Field(default_factory=dict)

class CallStarted(_Base): ...
class CallEnded(_Base):
    transcript: str | None = None
    ended_reason: str | None = None
class TranscriptChunk(_Base):
    role: str | None = None
    text: str
class ToolCall(_Base):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str | None = None
class ErrorEvent(_Base):
    message: str

WebhookEvent = CallStarted | CallEnded | TranscriptChunk | ToolCall | ErrorEvent
