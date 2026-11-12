from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    """Fields shared by every webhook event.

    Attributes:
        call_id: Provider call id the event belongs to.
        provider: Name of the provider that sent the event (``vapi`` or ``retell``).
        raw: Unmodified provider payload.
    """

    model_config = ConfigDict(extra="ignore")
    call_id: str | None = None
    provider: str
    raw: dict[str, Any] = Field(default_factory=dict)


class CallStarted(_Base):
    """A call has connected."""


class CallEnded(_Base):
    """A call has finished.

    Attributes:
        transcript: Full call transcript, if the provider included one.
        ended_reason: Provider-reported reason the call ended.
    """

    transcript: str | None = None
    ended_reason: str | None = None


class TranscriptChunk(_Base):
    """A piece of live transcript.

    Attributes:
        role: Speaker, for example ``user`` or ``assistant``.
        text: The transcribed text.
    """

    role: str | None = None
    text: str


class ToolCall(_Base):
    """The agent wants your server to run a tool.

    Answer it with ``VoiceClient.tool_response``.

    Attributes:
        name: Name of the tool to run.
        arguments: Arguments the model supplied.
        tool_call_id: Provider id to echo back in the response, if the provider uses one.
    """

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str | None = None


class ErrorEvent(_Base):
    """The provider reported an error.

    Attributes:
        message: Error description from the provider.
    """

    message: str


WebhookEvent = CallStarted | CallEnded | TranscriptChunk | ToolCall | ErrorEvent
