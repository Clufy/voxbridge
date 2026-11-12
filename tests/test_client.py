import json
import pathlib
from typing import Any

import httpx
import pytest
import respx

import voxbridge
from voxbridge.client import VoiceClient
from voxbridge.errors import NotSupported
from voxbridge.events import ToolCall
from voxbridge.models import Agent
from voxbridge.providers.retell import RetellProvider
from voxbridge.providers.vapi import VapiProvider

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
ASSISTANT = json.loads((FX / "assistant.json").read_text())


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        VoiceClient(provider="nope", api_key="k")


def test_selects_vapi() -> None:
    c = VoiceClient(provider="vapi", api_key="k")
    assert type(c._provider).__name__ == "VapiProvider"
    c.close()


def test_public_exports() -> None:
    for name in ("VoiceClient", "Agent", "Call", "Tool", "CallEnded", "WebhookEvent", "AuthError"):
        assert name in voxbridge.__all__
        assert hasattr(voxbridge, name)


@respx.mock
def test_delegates_create_agent() -> None:
    respx.post("https://api.vapi.ai/assistant").mock(
        return_value=httpx.Response(201, json=ASSISTANT)
    )
    c = VoiceClient("vapi", "k")
    a = c.create_agent(
        Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel")
    )
    assert a.id == ASSISTANT["id"]
    c.close()


class _SpyProvider:
    """Records close/aclose so context-manager delegation can be asserted."""

    def __init__(self) -> None:
        self.closed = False
        self.aclosed = False

    def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        self.aclosed = True


def test_sync_context_manager_closes_provider() -> None:
    c = VoiceClient("vapi", "k")
    spy = _SpyProvider()
    c._provider = spy  # type: ignore[assignment]
    with c as entered:
        assert entered is c
    assert spy.closed


async def test_async_context_manager_closes_provider() -> None:
    c = VoiceClient("vapi", "k")
    spy = _SpyProvider()
    c._provider = spy  # type: ignore[assignment]
    async with c as entered:
        assert entered is c
    assert spy.aclosed


def test_all_delegations_forward_to_provider() -> None:
    from unittest.mock import MagicMock

    c = VoiceClient("vapi", "k")
    m = MagicMock()
    c._provider = m

    agent = Agent(name="S", system_prompt="x", model="gpt-4o", voice="v")
    c.create_agent(agent)
    m.create_agent.assert_called_once_with(agent)
    c.update_agent("a1", agent)
    m.update_agent.assert_called_once_with("a1", agent)
    c.get_agent("a1")
    m.get_agent.assert_called_once_with("a1")
    c.delete_agent("a1")
    m.delete_agent.assert_called_once_with("a1")
    c.create_call("a1", "+1", from_number="+2")
    m.create_call.assert_called_once_with("a1", "+1", from_number="+2")
    c.get_call("c1")
    m.get_call.assert_called_once_with("c1")
    c.list_calls()
    m.list_calls.assert_called_once_with(limit=None)
    c.parse_webhook({"h": "v"}, b"{}")
    m.parse_webhook.assert_called_once_with({"h": "v"}, b"{}")
    c.verify_signature({"h": "v"}, b"{}")
    m.verify_signature.assert_called_once_with({"h": "v"}, b"{}")


async def test_all_async_delegations_forward_to_provider() -> None:
    from unittest.mock import AsyncMock

    c = VoiceClient("vapi", "k")
    m = AsyncMock()
    c._provider = m

    agent = Agent(name="S", system_prompt="x", model="gpt-4o", voice="v")
    await c.acreate_agent(agent)
    m.acreate_agent.assert_awaited_once_with(agent)
    await c.aupdate_agent("a1", agent)
    m.aupdate_agent.assert_awaited_once_with("a1", agent)
    await c.aget_agent("a1")
    m.aget_agent.assert_awaited_once_with("a1")
    await c.adelete_agent("a1")
    m.adelete_agent.assert_awaited_once_with("a1")
    await c.acreate_call("a1", "+1", from_number="+2")
    m.acreate_call.assert_awaited_once_with("a1", "+1", from_number="+2")
    await c.aget_call("c1")
    m.aget_call.assert_awaited_once_with("c1")
    await c.alist_calls()
    m.alist_calls.assert_awaited_once_with(limit=None)


def test_from_env_reads_provider_key_and_secret() -> None:
    c = VoiceClient.from_env(
        environ={"VOICE_PROVIDER": "vapi", "VAPI_API_KEY": "k", "VAPI_WEBHOOK_SECRET": "s"}
    )
    assert isinstance(c._provider, VapiProvider) and c._provider._webhook_secret == "s"


def test_from_env_missing_key_names_variable() -> None:
    with pytest.raises(ValueError, match="RETELL_API_KEY"):
        VoiceClient.from_env("retell", environ={})


def test_from_env_empty_key_counts_as_unset() -> None:
    with pytest.raises(ValueError, match="VAPI_API_KEY"):
        VoiceClient.from_env("vapi", environ={"VAPI_API_KEY": ""})


def test_from_env_unknown_provider_rejected_before_reading_env() -> None:
    with pytest.raises(ValueError, match="unknown provider"):
        VoiceClient.from_env("nope", environ={})


def test_from_env_missing_provider() -> None:
    with pytest.raises(ValueError, match="VOICE_PROVIDER"):
        VoiceClient.from_env(environ={})


def test_from_env_reads_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_PROVIDER", "retell")
    monkeypatch.setenv("RETELL_API_KEY", "k")
    assert isinstance(VoiceClient.from_env()._provider, RetellProvider)


def test_from_env_max_age_parsed_and_bad_value_rejected() -> None:
    env = {"RETELL_API_KEY": "k", "RETELL_WEBHOOK_MAX_AGE": "60"}
    assert VoiceClient.from_env("retell", environ=env)._provider._webhook_max_age == 60.0  # type: ignore[attr-defined]
    env["RETELL_WEBHOOK_MAX_AGE"] = "soon"
    with pytest.raises(ValueError, match="RETELL_WEBHOOK_MAX_AGE"):
        VoiceClient.from_env("retell", environ=env)


def test_from_env_empty_optional_values_are_unset() -> None:
    env = {"RETELL_API_KEY": "k", "RETELL_WEBHOOK_SECRET": "", "RETELL_WEBHOOK_MAX_AGE": ""}
    c = VoiceClient.from_env("retell", environ=env)
    assert c._provider._webhook_max_age == 300  # type: ignore[attr-defined]


def test_from_env_overrides_win() -> None:
    env = {"VAPI_API_KEY": "k", "VAPI_WEBHOOK_SECRET": "env"}
    c = VoiceClient.from_env("vapi", environ=env, timeout=5, webhook_secret="over")
    assert c._provider._webhook_secret == "over"  # type: ignore[attr-defined]
    assert c._provider._http._client().timeout == httpx.Timeout(5)  # type: ignore[attr-defined]


def test_from_env_api_key_override_makes_env_key_optional() -> None:
    c = VoiceClient.from_env("retell", environ={}, api_key="over")
    assert c._provider._webhook_secret == "over"  # type: ignore[attr-defined]
    c2 = VoiceClient.from_env("vapi", environ={"VAPI_API_KEY": "env"}, api_key="over")
    assert c2._provider._http._headers["Authorization"] == "Bearer over"  # type: ignore[attr-defined]


def test_from_env_provider_is_the_positional_argument() -> None:
    c = VoiceClient.from_env(provider="retell", environ={"RETELL_API_KEY": "k"})
    assert isinstance(c._provider, RetellProvider)
    # A second provider can't sneak in through **overrides: Python rejects it.
    extra: dict[str, Any] = {"provider": "retell"}
    with pytest.raises(TypeError, match="provider"):
        VoiceClient.from_env("vapi", environ={"VAPI_API_KEY": "k"}, **extra)


def test_from_env_override_max_age_wins_over_env() -> None:
    env = {"RETELL_API_KEY": "k", "RETELL_WEBHOOK_MAX_AGE": "60"}
    c = VoiceClient.from_env("retell", environ=env, webhook_max_age=None)
    assert c._provider._webhook_max_age is None  # type: ignore[attr-defined]


def test_from_env_vapi_max_age_env_raises_not_supported() -> None:
    with pytest.raises(NotSupported):
        VoiceClient.from_env("vapi", environ={"VAPI_API_KEY": "k", "VAPI_WEBHOOK_MAX_AGE": "60"})


@pytest.mark.parametrize("value", [300, None])
def test_vapi_with_max_age_raises_not_supported(value: float | None) -> None:
    with pytest.raises(NotSupported, match="no timestamp"):
        VoiceClient("vapi", "k", webhook_max_age=value)


def test_retell_default_max_age_is_300() -> None:
    assert VoiceClient("retell", "k")._provider._webhook_max_age == 300  # type: ignore[attr-defined]


def test_retell_explicit_none_disables_replay_check() -> None:
    c = VoiceClient("retell", "k", webhook_max_age=None)
    assert c._provider._webhook_max_age is None  # type: ignore[attr-defined]


def test_timeout_forwarded_to_provider() -> None:
    c = VoiceClient("vapi", "k", timeout=5)
    assert c._provider._http._client().timeout == httpx.Timeout(5)  # type: ignore[attr-defined]
    c.close()


def test_list_calls_limit_delegates() -> None:
    from unittest.mock import MagicMock

    c = VoiceClient("vapi", "k")
    m = MagicMock()
    c._provider = m
    c.list_calls(limit=5)
    m.list_calls.assert_called_once_with(limit=5)


async def test_alist_calls_limit_delegates() -> None:
    from unittest.mock import AsyncMock

    c = VoiceClient("vapi", "k")
    m = AsyncMock()
    c._provider = m
    await c.alist_calls(limit=5)
    m.alist_calls.assert_awaited_once_with(limit=5)


def test_tool_response_delegates() -> None:
    from unittest.mock import MagicMock

    c = VoiceClient("vapi", "k")
    m = MagicMock()
    m.tool_response.return_value = {"x": 1}
    c._provider = m
    ev = ToolCall(provider="vapi", call_id="c", name="n", tool_call_id="t", raw={})
    assert c.tool_response(ev, {"ok": True}) == {"x": 1}
    m.tool_response.assert_called_once_with(ev, {"ok": True})
