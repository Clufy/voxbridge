import httpx, pytest, respx
from voxbridge._http import HttpCore
from voxbridge.errors import AuthError, RateLimited, ProviderError

BASE = "https://api.example.com"

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
