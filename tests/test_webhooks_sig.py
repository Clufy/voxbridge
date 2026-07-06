import hashlib
import hmac
import time

from voxbridge.webhooks import header_get, verify_retell, verify_vapi


def test_vapi_shared_secret():
    assert verify_vapi({"X-Vapi-Secret": "s3cr3t"}, b"{}", "s3cr3t")
    assert not verify_vapi({"X-Vapi-Secret": "wrong"}, b"{}", "s3cr3t")


def test_vapi_header_case_insensitive():
    assert verify_vapi({"x-vapi-secret": "s3cr3t"}, b"{}", "s3cr3t")


def test_vapi_missing_header():
    assert not verify_vapi({}, b"{}", "s3cr3t")


def test_retell_hmac_roundtrip():
    secret, body, ts = "key", b'{"event":"call_ended"}', "1720000000000"
    digest = hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
    sig = f"v={ts},d={digest}"
    assert verify_retell({"x-retell-signature": sig}, body, secret)
    assert not verify_retell({"x-retell-signature": f"v={ts},d=deadbeef"}, body, secret)


def test_retell_missing_or_malformed_header():
    assert not verify_retell({}, b"{}", "key")
    assert not verify_retell({"x-retell-signature": "garbage"}, b"{}", "key")


def test_retell_max_age_rejects_old_and_accepts_fresh():
    secret, body = "key", b"{}"
    fresh_ts = str(int(time.time() * 1000))
    old_ts = str(int((time.time() - 3600) * 1000))
    for ts, ok in ((fresh_ts, True), (old_ts, False)):
        digest = hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
        sig = f"v={ts},d={digest}"
        assert verify_retell({"x-retell-signature": sig}, body, secret, max_age=300) is ok


def test_header_get_case_insensitive():
    assert header_get({"X-Foo": "bar"}, "x-foo") == "bar"
    assert header_get({"x-foo": "bar"}, "X-FOO") == "bar"
    assert header_get({}, "x-foo") is None
