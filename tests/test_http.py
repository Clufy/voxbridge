import httpx
import pytest
import respx

from voxbridge import _http
from voxbridge._http import HttpCore, _parse_retry_after
from voxbridge.errors import AuthError, ProviderError, RateLimited

BASE = "https://api.example.com"


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    def fake_sleep(d: float) -> None:
        recorded.append(d)

    async def fake_asleep(d: float) -> None:
        recorded.append(d)

    monkeypatch.setattr(_http, "_sleep", fake_sleep)
    monkeypatch.setattr(_http, "_asleep", fake_asleep)
    return recorded


@respx.mock
def test_get_ok():
    respx.get(f"{BASE}/thing").mock(return_value=httpx.Response(200, json={"id": "1"}))
    core = HttpCore(BASE, "k", "vapi")
    assert core.request("GET", "/thing") == {"id": "1"}
    core.close()

@respx.mock
def test_401_maps_to_auth_error():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(401, json={"message": "no"}))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(AuthError):
        core.request("GET", "/x")
    core.close()

@respx.mock
def test_429_maps_to_rate_limited_with_retry_after():
    respx.get(f"{BASE}/x").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "12"}, json={}))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(RateLimited) as ei:
        core.request("GET", "/x")
    assert ei.value.retry_after == 12.0
    core.close()

@respx.mock
async def test_async_request():
    respx.get(f"{BASE}/thing").mock(return_value=httpx.Response(200, json={"ok": True}))
    core = HttpCore(BASE, "k", "vapi")
    assert await core.arequest("GET", "/thing") == {"ok": True}
    await core.aclose()

@respx.mock
def test_retry_then_succeed():
    respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(500, json={}), httpx.Response(200, json={"ok": True})])
    core = HttpCore(BASE, "k", "vapi")
    assert core.request("GET", "/x") == {"ok": True}
    core.close()

@respx.mock
def test_generic_500_maps_to_provider_error():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(500, json={}))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError) as ei:
        core.request("GET", "/x")
    assert not isinstance(ei.value, AuthError)
    assert not isinstance(ei.value, RateLimited)
    core.close()

@respx.mock
def test_connect_error_maps_to_provider_error_after_retry():
    respx.get(f"{BASE}/x").mock(side_effect=httpx.ConnectError("boom"))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError) as ei:
        core.request("GET", "/x")
    assert ei.value.provider == "vapi"
    core.close()

@respx.mock
def test_204_returns_none():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(204))
    core = HttpCore(BASE, "k", "vapi")
    assert core.request("GET", "/x") is None
    core.close()

@respx.mock
def test_non_json_error_body_falls_back_to_text():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(500, text="upstream boom"))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError) as ei:
        core.request("GET", "/x")
    assert ei.value.body == "upstream boom"
    core.close()

@respx.mock
async def test_async_retry_then_succeed():
    respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(503, json={}), httpx.Response(200, json={"ok": True})])
    core = HttpCore(BASE, "k", "vapi")
    assert await core.arequest("GET", "/x") == {"ok": True}
    await core.aclose()

@respx.mock
async def test_async_generic_500_maps_to_provider_error():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(500, json={}))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError):
        await core.arequest("GET", "/x")
    await core.aclose()

@respx.mock
async def test_async_connect_error_maps_to_provider_error_after_retry():
    respx.get(f"{BASE}/x").mock(side_effect=httpx.ConnectError("boom"))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError) as ei:
        await core.arequest("GET", "/x")
    assert ei.value.provider == "vapi"
    await core.aclose()


def test_construction_builds_no_clients() -> None:
    core = HttpCore(BASE, "k", "vapi")
    assert core._sync_client is None and core._async_client is None
    core.close()


@respx.mock
def test_post_not_retried_on_500() -> None:
    route = respx.post(f"{BASE}/call").mock(return_value=httpx.Response(500, json={}))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError):
        core.request("POST", "/call", json={})
    assert route.call_count == 1


@respx.mock
def test_post_not_retried_on_read_timeout() -> None:
    route = respx.post(f"{BASE}/call").mock(side_effect=httpx.ReadTimeout("t"))
    with pytest.raises(ProviderError):
        HttpCore(BASE, "k", "vapi").request("POST", "/call", json={})
    assert route.call_count == 1


@respx.mock
def test_post_retried_on_connect_error() -> None:
    route = respx.post(f"{BASE}/call").mock(
        side_effect=[httpx.ConnectError("x"), httpx.Response(201, json={"id": "c"})])
    assert HttpCore(BASE, "k", "vapi").request("POST", "/call", json={}) == {"id": "c"}
    assert route.call_count == 2


@respx.mock
def test_post_retried_on_429_after_retry_after(sleeps: list[float]) -> None:
    respx.post(f"{BASE}/call").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(201, json={})])
    HttpCore(BASE, "k", "vapi").request("POST", "/call", json={})
    assert sleeps == [3.0]


@respx.mock
def test_idempotent_flag_allows_post_retry_on_500() -> None:
    route = respx.post(f"{BASE}/list").mock(
        side_effect=[httpx.Response(500, json={}), httpx.Response(200, json=[])])
    HttpCore(BASE, "k", "retell").request("POST", "/list", json={}, idempotent=True)
    assert route.call_count == 2


@respx.mock
def test_get_retry_waits_default_backoff(sleeps: list[float]) -> None:
    respx.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(500, json={}), httpx.Response(200, json={})])
    HttpCore(BASE, "k", "vapi").request("GET", "/x")
    assert sleeps == [0.5]


@respx.mock
def test_retry_after_capped_at_10(sleeps: list[float]) -> None:
    respx.get(f"{BASE}/x").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "120"}), httpx.Response(200, json={})])
    HttpCore(BASE, "k", "vapi").request("GET", "/x")
    assert sleeps == [10.0]


@respx.mock
def test_503_retry_after_sets_delay(sleeps: list[float]) -> None:
    respx.get(f"{BASE}/x").mock(side_effect=[
        httpx.Response(503, headers={"Retry-After": "2"}), httpx.Response(200, json={})])
    HttpCore(BASE, "k", "vapi").request("GET", "/x")
    assert sleeps == [2.0]


@pytest.mark.parametrize("value,expected", [
    ("12", 12.0), (None, None), ("soon", None), ("-5", 0.0),
    ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),
])
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    assert _parse_retry_after(value) == expected


@respx.mock
def test_429_with_http_date_retry_after_does_not_crash() -> None:
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(
        429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))
    with pytest.raises(RateLimited) as ei:
        HttpCore(BASE, "k", "vapi").request("GET", "/x")
    assert ei.value.retry_after == 0.0


def test_timeout_is_applied() -> None:
    core = HttpCore(BASE, "k", "vapi", timeout=7.5)
    assert core._client().timeout == httpx.Timeout(7.5)
    core.close()


@respx.mock
async def test_async_post_not_retried_on_500() -> None:
    route = respx.post(f"{BASE}/call").mock(return_value=httpx.Response(500, json={}))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError):
        await core.arequest("POST", "/call", json={})
    assert route.call_count == 1
    await core.aclose()


@respx.mock
async def test_async_post_retried_on_connect_error() -> None:
    route = respx.post(f"{BASE}/call").mock(
        side_effect=[httpx.ConnectError("x"), httpx.Response(201, json={"id": "c"})])
    core = HttpCore(BASE, "k", "vapi")
    assert await core.arequest("POST", "/call", json={}) == {"id": "c"}
    assert route.call_count == 2
    await core.aclose()


@respx.mock
async def test_async_429_backoff(sleeps: list[float]) -> None:
    respx.post(f"{BASE}/call").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(201, json={})])
    core = HttpCore(BASE, "k", "vapi")
    await core.arequest("POST", "/call", json={})
    assert sleeps == [3.0]
    await core.aclose()


@respx.mock
async def test_async_idempotent_flag_allows_post_retry_on_500() -> None:
    route = respx.post(f"{BASE}/list").mock(
        side_effect=[httpx.Response(500, json={}), httpx.Response(200, json=[])])
    core = HttpCore(BASE, "k", "retell")
    await core.arequest("POST", "/list", json={}, idempotent=True)
    assert route.call_count == 2
    await core.aclose()
