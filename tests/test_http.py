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
