"""voxbridge: one interface over multiple voice-agent platforms."""

from __future__ import annotations

from .client import VoiceClient
from .errors import (
    AuthError,
    NotSupported,
    ProviderError,
    RateLimited,
    SignatureError,
    VoxBridgeError,
)
from .events import (
    CallEnded,
    CallStarted,
    ErrorEvent,
    ToolCall,
    TranscriptChunk,
    WebhookEvent,
)
from .models import Agent, Call, Tool

__version__ = "0.1.0"

__all__ = [
    "VoiceClient",
    "Agent",
    "Call",
    "Tool",
    "CallStarted",
    "CallEnded",
    "TranscriptChunk",
    "ToolCall",
    "ErrorEvent",
    "WebhookEvent",
    "VoxBridgeError",
    "AuthError",
    "RateLimited",
    "ProviderError",
    "NotSupported",
    "SignatureError",
    "__version__",
]
