"""Vapi provider adapter: sync agent + call CRUD over Vapi's REST API.

Webhook parsing/verification (parse_webhook/verify_signature) and the async
twins of these methods are added in later tasks; this module intentionally
implements only the sync agent/call surface.
"""

from __future__ import annotations

from .._http import HttpCore
from ..models import Agent, Call
from ._vapi_map import agent_to_vapi, call_request, vapi_to_agent, vapi_to_call


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

    def close(self) -> None:
        self._http.close()
