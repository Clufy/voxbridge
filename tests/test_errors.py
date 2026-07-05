import pytest
from voxbridge.errors import (
    VoxBridgeError, AuthError, RateLimited, ProviderError, NotSupported, SignatureError,
)

def test_hierarchy():
    for exc in (AuthError, RateLimited, ProviderError, NotSupported, SignatureError):
        assert issubclass(exc, VoxBridgeError)

def test_rate_limited_carries_retry_after():
    e = RateLimited("slow down", status_code=429, provider="vapi", retry_after=30)
    assert e.retry_after == 30
    assert e.status_code == 429
    assert e.provider == "vapi"

def test_provider_error_carries_body():
    e = ProviderError("boom", status_code=500, provider="retell", body={"message": "x"})
    assert e.body == {"message": "x"}
