"""Shared normalization helpers used by more than one provider map."""

from __future__ import annotations

import json
from typing import Any

from ..errors import ProviderError

# Providers name the bot speaker differently (Vapi "assistant", Retell "agent").
# Normalize to one vocabulary so TranscriptChunk.role means the same thing
# regardless of provider. "user" passes through unchanged on both.
_ROLE_ALIASES = {"agent": "assistant"}


def normalize_role(role: str | None) -> str | None:
    if role is None:
        return None
    return _ROLE_ALIASES.get(role, role)


def decode_webhook_body(raw_body: bytes, provider: str) -> dict[str, Any]:
    """Decode a raw webhook body to a JSON object, raising a typed error.

    A malformed or non-object body is untrusted input at a trust boundary, so
    it must surface as a VoxBridgeError (ProviderError) — never a bare
    JSONDecodeError/AttributeError that escapes a caller's `except VoxBridgeError`.
    """
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ProviderError("webhook body is not valid JSON", provider=provider) from exc
    if not isinstance(payload, dict):
        raise ProviderError("webhook payload must be a JSON object", provider=provider)
    return payload
