"""VoiceClient: the public facade over provider adapters.

Picks a provider by config string and delegates every call to that adapter.
Only "vapi" is registered today; Task 11 adds "retell" as a one-line change
to ``_PROVIDERS``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from .events import WebhookEvent
from .models import Agent, Call
from .providers.base import VoiceProvider
from .providers.vapi import VapiProvider

# VapiProvider doesn't yet implement the full VoiceProvider protocol (webhook
# parsing/verification and async twins land in Tasks 13/15); the cast reflects
# that the registry's job is only to construct adapters, not to enforce
# completeness of the protocol at registration time.
# Task 11 adds "retell": RetellProvider
_PROVIDERS: dict[str, Callable[..., VoiceProvider]] = {
    "vapi": cast(Callable[..., VoiceProvider], VapiProvider)
}


class VoiceClient:
    """Provider-agnostic entry point: same API regardless of backend."""

    def __init__(
        self, provider: str, api_key: str, *, webhook_secret: str | None = None
    ) -> None:
        try:
            provider_cls = _PROVIDERS[provider]
        except KeyError:
            raise ValueError(
                f"unknown provider {provider!r}; choose from {sorted(_PROVIDERS)}"
            ) from None
        self._provider: VoiceProvider = provider_cls(api_key, webhook_secret=webhook_secret)

    # -- sync -----------------------------------------------------------

    def create_agent(self, agent: Agent) -> Agent:
        return self._provider.create_agent(agent)

    def update_agent(self, agent_id: str, agent: Agent) -> Agent:
        return self._provider.update_agent(agent_id, agent)

    def get_agent(self, agent_id: str) -> Agent:
        return self._provider.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> None:
        return self._provider.delete_agent(agent_id)

    def create_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        return self._provider.create_call(agent_id, to_number, from_number=from_number)

    def get_call(self, call_id: str) -> Call:
        return self._provider.get_call(call_id)

    def list_calls(self) -> list[Call]:
        return self._provider.list_calls()

    def parse_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> WebhookEvent:
        return self._provider.parse_webhook(headers, raw_body)

    def verify_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        return self._provider.verify_signature(headers, raw_body)

    def close(self) -> None:
        self._provider.close()

    # -- async ------------------------------------------------------------

    async def acreate_agent(self, agent: Agent) -> Agent:
        return await self._provider.acreate_agent(agent)

    async def aupdate_agent(self, agent_id: str, agent: Agent) -> Agent:
        return await self._provider.aupdate_agent(agent_id, agent)

    async def aget_agent(self, agent_id: str) -> Agent:
        return await self._provider.aget_agent(agent_id)

    async def adelete_agent(self, agent_id: str) -> None:
        return await self._provider.adelete_agent(agent_id)

    async def acreate_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        return await self._provider.acreate_call(agent_id, to_number, from_number=from_number)

    async def aget_call(self, call_id: str) -> Call:
        return await self._provider.aget_call(call_id)

    async def alist_calls(self) -> list[Call]:
        return await self._provider.alist_calls()

    async def aclose(self) -> None:
        await self._provider.aclose()

    # -- context managers -------------------------------------------------

    def __enter__(self) -> VoiceClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    async def __aenter__(self) -> VoiceClient:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()
