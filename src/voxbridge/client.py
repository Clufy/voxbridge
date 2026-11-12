"""VoiceClient: the public facade over provider adapters.

Picks a provider by config string and delegates every call to that adapter.
Both "vapi" and "retell" are registered.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from .errors import NotSupported
from .events import ToolCall, WebhookEvent
from .models import Agent, Call
from .providers.base import VoiceProvider
from .providers.retell import RetellProvider
from .providers.vapi import VapiProvider

_PROVIDERS: dict[str, Callable[..., VoiceProvider]] = {
    "vapi": VapiProvider,
    "retell": RetellProvider,
}


class _Unset:
    """Type of the module-private sentinel meaning "argument not passed"."""

    def __repr__(self) -> str:
        return "UNSET"


_UNSET = _Unset()

_VAPI_NO_MAX_AGE = (
    "webhook_max_age: Vapi webhooks carry no timestamp, "
    "so replay protection isn't available"
)


class VoiceClient:
    """Provider-agnostic entry point: same API regardless of backend.

    Requests are retried at most once. Connect errors, connect timeouts and 429
    responses are retried for any request; read/write timeouts, 500/502/503/504
    responses and other request errors only for idempotent requests. A ``Retry-After``
    header is honoured, capped at 10 seconds. Capabilities a provider lacks raise ``NotSupported``.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        *,
        webhook_secret: str | None = None,
        webhook_max_age: float | None | _Unset = _UNSET,
        timeout: float = 30.0,
    ) -> None:
        """Create a client for one provider.

        Args:
            provider: Provider name, "vapi" or "retell".
            api_key: The provider API key.
            webhook_secret: Secret used to verify webhooks. Retell falls back
                to the API key when omitted.
            webhook_max_age: Retell only. Max webhook signature age in
                seconds (default 300); None disables the replay check.
            timeout: Per-request HTTP timeout in seconds.

        Raises:
            ValueError: If the provider name is unknown.
            NotSupported: If webhook_max_age is passed for Vapi.
        """
        try:
            provider_cls = _PROVIDERS[provider]
        except KeyError:
            raise ValueError(
                f"unknown provider {provider!r}; choose from {sorted(_PROVIDERS)}"
            ) from None
        kwargs: dict[str, Any] = {"webhook_secret": webhook_secret, "timeout": timeout}
        if not isinstance(webhook_max_age, _Unset):
            if provider != "retell":
                raise NotSupported(_VAPI_NO_MAX_AGE)
            kwargs["webhook_max_age"] = webhook_max_age
        self._provider: VoiceProvider = provider_cls(api_key, **kwargs)

    @classmethod
    def from_env(
        cls,
        provider: str | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> VoiceClient:
        """Build a client from environment variables.

        Reads VOICE_PROVIDER (unless provider is given), then
        <P>_API_KEY, <P>_WEBHOOK_SECRET and <P>_WEBHOOK_MAX_AGE where <P> is
        the upper-cased provider name. Empty values count as unset.

        Args:
            provider: Provider name; defaults to VOICE_PROVIDER.
            environ: Mapping to read instead of os.environ.
            **overrides: Keyword arguments for the constructor (api_key,
                webhook_secret, webhook_max_age, timeout); they win over
                environment values. With an api_key override, <P>_API_KEY
                is not required.

        Raises:
            ValueError: If the provider or API key is missing, or
                <P>_WEBHOOK_MAX_AGE is not a number.
            NotSupported: If <P>_WEBHOOK_MAX_AGE is set for Vapi.
        """
        env = os.environ if environ is None else environ
        name = provider or env.get("VOICE_PROVIDER")
        if not name:
            raise ValueError("set VOICE_PROVIDER or pass provider=...")
        if name not in _PROVIDERS:
            raise ValueError(f"unknown provider {name!r}; choose from {sorted(_PROVIDERS)}")
        prefix = name.upper()
        api_key = overrides.pop("api_key", None) or env.get(f"{prefix}_API_KEY")
        if not api_key:
            raise ValueError(f"{prefix}_API_KEY is not set")
        kwargs: dict[str, Any] = {}
        secret = env.get(f"{prefix}_WEBHOOK_SECRET")
        if secret:
            kwargs["webhook_secret"] = secret
        max_age = env.get(f"{prefix}_WEBHOOK_MAX_AGE")
        if max_age:
            try:
                kwargs["webhook_max_age"] = float(max_age)
            except ValueError:
                raise ValueError(
                    f"{prefix}_WEBHOOK_MAX_AGE must be a number, got {max_age!r}"
                ) from None
        kwargs.update(overrides)
        return cls(name, api_key, **kwargs)

    # -- sync -----------------------------------------------------------

    def create_agent(self, agent: Agent) -> Agent:
        """Create an agent on the provider and return it with its id."""
        return self._provider.create_agent(agent)

    def update_agent(self, agent_id: str, agent: Agent) -> Agent:
        """Update an existing agent from the given definition and return it."""
        return self._provider.update_agent(agent_id, agent)

    def get_agent(self, agent_id: str) -> Agent:
        """Fetch an agent by id."""
        return self._provider.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> None:
        """Delete an agent by id."""
        return self._provider.delete_agent(agent_id)

    def create_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        """Start an outbound call.

        Args:
            agent_id: The agent that will handle the call.
            to_number: Destination number in E.164 format.
            from_number: Caller number; needed for outbound calls on both
                providers. Retell requires an E.164 number (ValueError if
                missing). On Vapi pass an E.164 number, looked up among your
                phone numbers, or a phone-number id.

        Raises:
            ValueError: On Retell, if from_number is missing.
            ProviderError: On Vapi, if no phone number matches from_number.
        """
        return self._provider.create_call(agent_id, to_number, from_number=from_number)

    def get_call(self, call_id: str) -> Call:
        """Fetch a call by id."""
        return self._provider.get_call(call_id)

    def list_calls(self, *, limit: int | None = None) -> list[Call]:
        """List calls.

        Args:
            limit: Maximum number of calls to return; None uses the provider default.
        """
        return self._provider.list_calls(limit=limit)

    def parse_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> WebhookEvent:
        """Verify a webhook request and parse it into an event.

        Args:
            headers: The request headers.
            raw_body: The unmodified request body bytes.

        Raises:
            SignatureError: If verification fails.
            ProviderError: If the body is not JSON or not a webhook of the
                expected shape.
        """
        return self._provider.parse_webhook(headers, raw_body)

    def verify_signature(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Return True if the webhook request is authentic, without parsing it."""
        return self._provider.verify_signature(headers, raw_body)

    def tool_response(self, event: ToolCall, result: Any) -> Any:
        """Build the HTTP response body to return for a tool call.

        Args:
            event: The ToolCall event parsed from the webhook.
            result: The tool's result; must be JSON-serialisable.
        """
        return self._provider.tool_response(event, result)

    def close(self) -> None:
        """Close the provider's sync HTTP client."""
        self._provider.close()

    # -- async ------------------------------------------------------------

    async def acreate_agent(self, agent: Agent) -> Agent:
        """Async twin of create_agent."""
        return await self._provider.acreate_agent(agent)

    async def aupdate_agent(self, agent_id: str, agent: Agent) -> Agent:
        """Async twin of update_agent."""
        return await self._provider.aupdate_agent(agent_id, agent)

    async def aget_agent(self, agent_id: str) -> Agent:
        """Async twin of get_agent."""
        return await self._provider.aget_agent(agent_id)

    async def adelete_agent(self, agent_id: str) -> None:
        """Async twin of delete_agent."""
        return await self._provider.adelete_agent(agent_id)

    async def acreate_call(
        self, agent_id: str, to_number: str, *, from_number: str | None = None
    ) -> Call:
        """Async twin of create_call."""
        return await self._provider.acreate_call(agent_id, to_number, from_number=from_number)

    async def aget_call(self, call_id: str) -> Call:
        """Async twin of get_call."""
        return await self._provider.aget_call(call_id)

    async def alist_calls(self, *, limit: int | None = None) -> list[Call]:
        """Async twin of list_calls."""
        return await self._provider.alist_calls(limit=limit)

    async def aclose(self) -> None:
        """Close the provider's async HTTP client."""
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
