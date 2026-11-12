"""Vapi provider adapter: agent + call CRUD over Vapi's REST API.

Every sync method has an ``a``-prefixed async twin; webhook parse/verify and
tool-response helpers live here too.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._http import HttpCore
from ..errors import ProviderError, SignatureError
from ..events import ToolCall, WebhookEvent
from ..models import Agent, Call
from ..webhooks import verify_vapi
from ._common import decode_webhook_body
from ._vapi_map import (
    agent_to_vapi,
    call_request,
    find_phone_number_id,
    merge_vapi_update,
    parse_webhook,
    vapi_to_agent,
    vapi_to_call,
    vapi_tool_response,
)


def _limit_params(limit: int | None) -> dict[str, int] | None:
    return None if limit is None else {"limit": limit}


def _resolve_number(numbers: list[dict[str, Any]], e164: str) -> str:
    phone_id = find_phone_number_id(numbers, e164)
    if phone_id is None:
        raise ProviderError(f"no Vapi phone number matches {e164}", provider="vapi")
    return phone_id


class VapiProvider:
    """Voice provider adapter for Vapi (https://api.vapi.ai)."""

    def __init__(
        self, api_key: str, *, webhook_secret: str | None = None, timeout: float = 30.0
    ) -> None:
        self._http = HttpCore("https://api.vapi.ai", api_key, "vapi", timeout=timeout)
        self._webhook_secret = webhook_secret

    def create_agent(self, agent: Agent) -> Agent:
        """Create an agent and return it with its provider id."""
        data = self._http.request("POST", "/assistant", json=agent_to_vapi(agent))
        return vapi_to_agent(data)

    def update_agent(self, agent_id: str, agent: Agent) -> Agent:
        """Update an existing agent and return the result."""
        existing = self._http.request("GET", f"/assistant/{agent_id}")
        data = self._http.request(
            "PATCH", f"/assistant/{agent_id}", json=merge_vapi_update(existing, agent)
        )
        return vapi_to_agent(data)

    def get_agent(self, agent_id: str) -> Agent:
        """Fetch an agent by id."""
        data = self._http.request("GET", f"/assistant/{agent_id}")
        return vapi_to_agent(data)

    def delete_agent(self, agent_id: str) -> None:
        """Delete an agent by id."""
        self._http.request("DELETE", f"/assistant/{agent_id}")
        return None

    def create_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        """Place an outbound call from an agent to ``to_number``."""
        if from_number is not None and from_number.startswith("+"):
            numbers = self._http.request("GET", "/phone-number")
            from_number = _resolve_number(numbers, from_number)
        data = self._http.request(
            "POST", "/call", json=call_request(agent_id, to_number, from_number)
        )
        return vapi_to_call(data)

    def get_call(self, call_id: str) -> Call:
        """Fetch a call by id."""
        data = self._http.request("GET", f"/call/{call_id}")
        return vapi_to_call(data)

    def list_calls(self, *, limit: int | None = None) -> list[Call]:
        """List calls, optionally capped at ``limit``."""
        data = self._http.request("GET", "/call", params=_limit_params(limit))
        return [vapi_to_call(item) for item in data]

    def verify_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Return whether the webhook signature is valid."""
        if self._webhook_secret is None:
            return True
        return verify_vapi(headers, raw_body, self._webhook_secret)

    def parse_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> WebhookEvent:
        """Verify and parse a webhook into a normalized event.

        Raises:
            SignatureError: If signature verification fails.
        """
        if self._webhook_secret is not None and not self.verify_signature(headers, raw_body):
            raise SignatureError("vapi webhook signature verification failed")
        return parse_webhook(decode_webhook_body(raw_body, "vapi"))

    def tool_response(self, event: ToolCall, result: Any) -> dict[str, Any]:
        """Build the response body this provider expects for a tool call."""
        return vapi_tool_response(event, result)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    # -- async twins: same mapping helpers, only the HTTP call differs -----

    async def acreate_agent(self, agent: Agent) -> Agent:
        """Async version of ``create_agent``."""
        data = await self._http.arequest("POST", "/assistant", json=agent_to_vapi(agent))
        return vapi_to_agent(data)

    async def aupdate_agent(self, agent_id: str, agent: Agent) -> Agent:
        """Async version of ``update_agent``."""
        existing = await self._http.arequest("GET", f"/assistant/{agent_id}")
        data = await self._http.arequest(
            "PATCH", f"/assistant/{agent_id}", json=merge_vapi_update(existing, agent)
        )
        return vapi_to_agent(data)

    async def aget_agent(self, agent_id: str) -> Agent:
        """Async version of ``get_agent``."""
        data = await self._http.arequest("GET", f"/assistant/{agent_id}")
        return vapi_to_agent(data)

    async def adelete_agent(self, agent_id: str) -> None:
        """Async version of ``delete_agent``."""
        await self._http.arequest("DELETE", f"/assistant/{agent_id}")
        return None

    async def acreate_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        """Async version of ``create_call``."""
        if from_number is not None and from_number.startswith("+"):
            numbers = await self._http.arequest("GET", "/phone-number")
            from_number = _resolve_number(numbers, from_number)
        data = await self._http.arequest(
            "POST", "/call", json=call_request(agent_id, to_number, from_number)
        )
        return vapi_to_call(data)

    async def aget_call(self, call_id: str) -> Call:
        """Async version of ``get_call``."""
        data = await self._http.arequest("GET", f"/call/{call_id}")
        return vapi_to_call(data)

    async def alist_calls(self, *, limit: int | None = None) -> list[Call]:
        """Async version of ``list_calls``."""
        data = await self._http.arequest("GET", "/call", params=_limit_params(limit))
        return [vapi_to_call(item) for item in data]

    async def aclose(self) -> None:
        """Async version of ``close``."""
        await self._http.aclose()
