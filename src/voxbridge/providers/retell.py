"""Retell provider adapter: agent + call CRUD over the Retell REST API.

Every sync method has an ``a``-prefixed async twin. Retell keeps the prompt,
greeting, model and tools on a separate LLM object, so get/update/create touch
both the agent and its LLM. Webhooks are always verified (with ``webhook_secret``
or, failing that, the API key).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._http import HttpCore
from ..errors import NotSupported, SignatureError, VoxBridgeError
from ..events import ToolCall, WebhookEvent
from ..models import Agent, Call
from ..webhooks import verify_retell
from ._common import decode_webhook_body
from ._retell_map import (
    agent_to_llm,
    agent_to_retell,
    llm_id_of,
    llm_update_body,
    parse_webhook,
    phone_call_request,
    retell_call_items,
    retell_to_agent,
    retell_to_call,
    retell_tool_response,
    voice_to_retell,
)

_NO_FROM_NUMBER = "Retell requires from_number for outbound calls"


def _list_body(limit: int | None) -> dict[str, int]:
    return {} if limit is None else {"limit": limit}


def _no_llm_engine(agent_id: str) -> NotSupported:
    return NotSupported(
        f"retell agent {agent_id} has no retell-llm response engine; "
        "prompt, model, greeting and tools can't be updated"
    )


def _agent_patch(agent: Agent) -> dict[str, str]:
    return {"agent_name": agent.name, "voice_id": voice_to_retell(agent.voice)}


class RetellProvider:
    """Voice provider adapter for Retell (https://api.retellai.com)."""

    def __init__(
        self,
        api_key: str,
        *,
        webhook_secret: str | None = None,
        webhook_max_age: float | None = 300.0,
        timeout: float = 30.0,
    ) -> None:
        self._http = HttpCore("https://api.retellai.com", api_key, "retell", timeout=timeout)
        # Retell signs webhooks with the API key unless a dedicated secret is given.
        self._webhook_secret = webhook_secret if webhook_secret is not None else api_key
        # Replay window in seconds; None disables the check.
        self._webhook_max_age = webhook_max_age

    def create_agent(self, agent: Agent) -> Agent:
        """Create an agent and return it with its provider id."""
        # Retell splits the prompt/greeting onto a separate LLM object, so
        # creating an agent takes two calls: create the LLM, then the agent
        # that references it via response_engine.llm_id.
        llm = self._http.request("POST", "/create-retell-llm", json=agent_to_llm(agent))
        try:
            data = self._http.request(
                "POST", "/create-agent", json=agent_to_retell(agent, llm["llm_id"])
            )
        except VoxBridgeError:
            # Don't leave an orphaned LLM behind; best effort, original error wins.
            try:
                self._http.request("DELETE", f"/delete-retell-llm/{llm['llm_id']}")
            except VoxBridgeError:
                pass
            raise
        return retell_to_agent(data, llm)

    def update_agent(self, agent_id: str, agent: Agent) -> Agent:
        """Update an existing agent and return the result."""
        existing = self._http.request("GET", f"/get-agent/{agent_id}")
        llm_id = llm_id_of(existing)
        if llm_id is None:
            raise _no_llm_engine(agent_id)
        existing_llm = self._http.request("GET", f"/get-retell-llm/{llm_id}")
        llm = self._http.request(
            "PATCH", f"/update-retell-llm/{llm_id}", json=llm_update_body(agent, existing_llm)
        )
        data = self._http.request("PATCH", f"/update-agent/{agent_id}", json=_agent_patch(agent))
        return retell_to_agent(data, llm)

    def get_agent(self, agent_id: str) -> Agent:
        """Fetch an agent by id."""
        data = self._http.request("GET", f"/get-agent/{agent_id}")
        llm_id = llm_id_of(data)
        llm = self._http.request("GET", f"/get-retell-llm/{llm_id}") if llm_id else None
        return retell_to_agent(data, llm)

    def delete_agent(self, agent_id: str) -> None:
        """Delete an agent by id."""
        self._http.request("DELETE", f"/delete-agent/{agent_id}")
        return None

    def create_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        """Place an outbound call from an agent to ``to_number``."""
        if from_number is None:
            raise ValueError(_NO_FROM_NUMBER)
        data = self._http.request(
            "POST",
            "/v2/create-phone-call",
            json=phone_call_request(agent_id, to_number, from_number),
        )
        return retell_to_call(data)

    def get_call(self, call_id: str) -> Call:
        """Fetch a call by id."""
        data = self._http.request("GET", f"/v2/get-call/{call_id}")
        return retell_to_call(data)

    def list_calls(self, *, limit: int | None = None) -> list[Call]:
        """List calls, optionally capped at ``limit``."""
        data = self._http.request(
            "POST", "/v3/list-calls", json=_list_body(limit), idempotent=True
        )
        return [retell_to_call(item) for item in retell_call_items(data)]

    def verify_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Return whether the webhook signature is valid."""
        return verify_retell(
            headers, raw_body, self._webhook_secret, max_age=self._webhook_max_age
        )

    def parse_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> WebhookEvent:
        """Verify and parse a webhook into a normalized event.

        Raises:
            SignatureError: If signature verification fails.
        """
        if not self.verify_signature(headers, raw_body):
            raise SignatureError("retell webhook signature verification failed")
        return parse_webhook(decode_webhook_body(raw_body, "retell"))

    def tool_response(self, event: ToolCall, result: Any) -> Any:
        """Build the response body this provider expects for a tool call."""
        return retell_tool_response(event, result)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    # -- async twins: same mapping helpers, only the HTTP call differs -----

    async def acreate_agent(self, agent: Agent) -> Agent:
        """Async version of ``create_agent``."""
        llm = await self._http.arequest(
            "POST", "/create-retell-llm", json=agent_to_llm(agent)
        )
        try:
            data = await self._http.arequest(
                "POST", "/create-agent", json=agent_to_retell(agent, llm["llm_id"])
            )
        except VoxBridgeError:
            try:
                await self._http.arequest("DELETE", f"/delete-retell-llm/{llm['llm_id']}")
            except VoxBridgeError:
                pass
            raise
        return retell_to_agent(data, llm)

    async def aupdate_agent(self, agent_id: str, agent: Agent) -> Agent:
        """Async version of ``update_agent``."""
        existing = await self._http.arequest("GET", f"/get-agent/{agent_id}")
        llm_id = llm_id_of(existing)
        if llm_id is None:
            raise _no_llm_engine(agent_id)
        existing_llm = await self._http.arequest("GET", f"/get-retell-llm/{llm_id}")
        llm = await self._http.arequest(
            "PATCH", f"/update-retell-llm/{llm_id}", json=llm_update_body(agent, existing_llm)
        )
        data = await self._http.arequest(
            "PATCH", f"/update-agent/{agent_id}", json=_agent_patch(agent)
        )
        return retell_to_agent(data, llm)

    async def aget_agent(self, agent_id: str) -> Agent:
        """Async version of ``get_agent``."""
        data = await self._http.arequest("GET", f"/get-agent/{agent_id}")
        llm_id = llm_id_of(data)
        llm = await self._http.arequest("GET", f"/get-retell-llm/{llm_id}") if llm_id else None
        return retell_to_agent(data, llm)

    async def adelete_agent(self, agent_id: str) -> None:
        """Async version of ``delete_agent``."""
        await self._http.arequest("DELETE", f"/delete-agent/{agent_id}")
        return None

    async def acreate_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        """Async version of ``create_call``."""
        if from_number is None:
            raise ValueError(_NO_FROM_NUMBER)
        data = await self._http.arequest(
            "POST",
            "/v2/create-phone-call",
            json=phone_call_request(agent_id, to_number, from_number),
        )
        return retell_to_call(data)

    async def aget_call(self, call_id: str) -> Call:
        """Async version of ``get_call``."""
        data = await self._http.arequest("GET", f"/v2/get-call/{call_id}")
        return retell_to_call(data)

    async def alist_calls(self, *, limit: int | None = None) -> list[Call]:
        """Async version of ``list_calls``."""
        data = await self._http.arequest(
            "POST", "/v3/list-calls", json=_list_body(limit), idempotent=True
        )
        return [retell_to_call(item) for item in retell_call_items(data)]

    async def aclose(self) -> None:
        """Async version of ``close``."""
        await self._http.aclose()
