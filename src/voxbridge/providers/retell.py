"""Retell provider adapter: sync agent + call CRUD over Retell's REST API.

The async twins of these methods are added in a later task; this module
implements the sync agent/call surface plus webhook parse/verify.
"""

from __future__ import annotations

from collections.abc import Mapping

from .._http import HttpCore
from ..errors import SignatureError
from ..events import WebhookEvent
from ..models import Agent, Call
from ..webhooks import verify_retell
from ._common import decode_webhook_body
from ._retell_map import (
    agent_to_llm,
    agent_to_retell,
    parse_webhook,
    phone_call_request,
    retell_to_agent,
    retell_to_call,
)


class RetellProvider:
    """Voice provider adapter for Retell (https://api.retellai.com)."""

    def __init__(
        self,
        api_key: str,
        *,
        webhook_secret: str | None = None,
        webhook_max_age: float | None = None,
    ) -> None:
        self._http = HttpCore("https://api.retellai.com", api_key, "retell")
        self._webhook_secret = webhook_secret
        # Optional replay window (seconds). Reject validly-signed but stale
        # deliveries when set. Off by default to stay deterministic in tests.
        self._webhook_max_age = webhook_max_age

    def create_agent(self, agent: Agent) -> Agent:
        # Retell splits the prompt/greeting onto a separate LLM object, so
        # creating an agent takes two calls: create the LLM, then the agent
        # that references it via response_engine.llm_id.
        llm = self._http.request("POST", "/create-retell-llm", json=agent_to_llm(agent))
        data = self._http.request(
            "POST", "/create-agent", json=agent_to_retell(agent, llm["llm_id"])
        )
        return retell_to_agent(data, llm)

    def update_agent(self, agent_id: str, agent: Agent) -> Agent:
        # Updating the prompt/greeting would require the LLM id, which the
        # domain model doesn't carry, so update covers agent-level fields only.
        data = self._http.request(
            "PATCH",
            f"/update-agent/{agent_id}",
            json={"agent_name": agent.name, "voice_id": agent.voice},
        )
        return retell_to_agent(data)

    def get_agent(self, agent_id: str) -> Agent:
        data = self._http.request("GET", f"/get-agent/{agent_id}")
        return retell_to_agent(data)

    def delete_agent(self, agent_id: str) -> None:
        self._http.request("DELETE", f"/delete-agent/{agent_id}")
        return None

    def create_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        data = self._http.request(
            "POST",
            "/v2/create-phone-call",
            json=phone_call_request(agent_id, to_number, from_number),
        )
        return retell_to_call(data)

    def get_call(self, call_id: str) -> Call:
        data = self._http.request("GET", f"/v2/get-call/{call_id}")
        return retell_to_call(data)

    def list_calls(self) -> list[Call]:
        data = self._http.request("POST", "/v3/list-calls", json={})
        items = data["calls"] if isinstance(data, dict) else data
        return [retell_to_call(item) for item in items]

    def verify_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        if self._webhook_secret is None:
            return True
        return verify_retell(
            headers, raw_body, self._webhook_secret, max_age=self._webhook_max_age
        )

    def parse_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> WebhookEvent:
        if self._webhook_secret is not None and not self.verify_signature(headers, raw_body):
            raise SignatureError("retell webhook signature verification failed")
        return parse_webhook(decode_webhook_body(raw_body, "retell"))

    def close(self) -> None:
        self._http.close()
