"""Vapi provider adapter: sync agent + call CRUD over Vapi's REST API.

The async twins of these methods are added in a later task; this module
implements the sync agent/call surface plus webhook parse/verify.
"""

from __future__ import annotations

from collections.abc import Mapping

from .._http import HttpCore
from ..errors import SignatureError
from ..events import WebhookEvent
from ..models import Agent, Call
from ..webhooks import verify_vapi
from ._common import decode_webhook_body
from ._vapi_map import agent_to_vapi, call_request, parse_webhook, vapi_to_agent, vapi_to_call


class VapiProvider:
    """Voice provider adapter for Vapi (https://api.vapi.ai)."""

    def __init__(self, api_key: str, *, webhook_secret: str | None = None) -> None:
        self._http = HttpCore("https://api.vapi.ai", api_key, "vapi")
        self._webhook_secret = webhook_secret

    def create_agent(self, agent: Agent) -> Agent:
        data = self._http.request("POST", "/assistant", json=agent_to_vapi(agent))
        return vapi_to_agent(data)

    def update_agent(self, agent_id: str, agent: Agent) -> Agent:
        data = self._http.request(
            "PATCH", f"/assistant/{agent_id}", json=agent_to_vapi(agent)
        )
        return vapi_to_agent(data)

    def get_agent(self, agent_id: str) -> Agent:
        data = self._http.request("GET", f"/assistant/{agent_id}")
        return vapi_to_agent(data)

    def delete_agent(self, agent_id: str) -> None:
        self._http.request("DELETE", f"/assistant/{agent_id}")
        return None

    def create_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        data = self._http.request(
            "POST", "/call", json=call_request(agent_id, to_number, from_number)
        )
        return vapi_to_call(data)

    def get_call(self, call_id: str) -> Call:
        data = self._http.request("GET", f"/call/{call_id}")
        return vapi_to_call(data)

    def list_calls(self) -> list[Call]:
        data = self._http.request("GET", "/call")
        return [vapi_to_call(item) for item in data]

    def verify_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        if self._webhook_secret is None:
            return True
        return verify_vapi(headers, raw_body, self._webhook_secret)

    def parse_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> WebhookEvent:
        if self._webhook_secret is not None and not self.verify_signature(headers, raw_body):
            raise SignatureError("vapi webhook signature verification failed")
        return parse_webhook(decode_webhook_body(raw_body, "vapi"))

    def close(self) -> None:
        self._http.close()

    # -- async twins: same mapping helpers, only the HTTP call differs -----

    async def acreate_agent(self, agent: Agent) -> Agent:
        data = await self._http.arequest("POST", "/assistant", json=agent_to_vapi(agent))
        return vapi_to_agent(data)

    async def aupdate_agent(self, agent_id: str, agent: Agent) -> Agent:
        data = await self._http.arequest(
            "PATCH", f"/assistant/{agent_id}", json=agent_to_vapi(agent)
        )
        return vapi_to_agent(data)

    async def aget_agent(self, agent_id: str) -> Agent:
        data = await self._http.arequest("GET", f"/assistant/{agent_id}")
        return vapi_to_agent(data)

    async def adelete_agent(self, agent_id: str) -> None:
        await self._http.arequest("DELETE", f"/assistant/{agent_id}")
        return None

    async def acreate_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        data = await self._http.arequest(
            "POST", "/call", json=call_request(agent_id, to_number, from_number)
        )
        return vapi_to_call(data)

    async def aget_call(self, call_id: str) -> Call:
        data = await self._http.arequest("GET", f"/call/{call_id}")
        return vapi_to_call(data)

    async def alist_calls(self) -> list[Call]:
        data = await self._http.arequest("GET", "/call")
        return [vapi_to_call(item) for item in data]

    async def aclose(self) -> None:
        await self._http.aclose()
