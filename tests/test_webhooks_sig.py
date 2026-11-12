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


def test_verify_vapi_bearer_header_accepted():
    assert verify_vapi({"authorization": "Bearer s3cr3t"}, b"{}", "s3cr3t")


def test_verify_vapi_wrong_bearer_rejected():
    assert not verify_vapi({"Authorization": "Bearer nope"}, b"{}", "s3cr3t")
    assert not verify_vapi({"Authorization": "s3cr3t"}, b"{}", "s3cr3t")


def test_verify_vapi_either_header_suffices():
    headers = {"X-Vapi-Secret": "wrong", "Authorization": "Bearer s3cr3t"}
    assert verify_vapi(headers, b"{}", "s3cr3t")


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


def _retell_sig(body: bytes, secret: str, ts: str) -> str:
    digest = hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
    return f"v={ts},d={digest}"


def test_retell_non_ascii_digest_rejected_not_type_error() -> None:
    assert not verify_retell({"x-retell-signature": "v=1,d=é"}, b"{}", "key")


def test_retell_rejects_non_canonical_shapes() -> None:
    body, ts = b"{}", "1720000000000"
    good = _retell_sig(body, "key", ts)
    digest = good.split("d=", 1)[1]
    assert verify_retell({"x-retell-signature": good}, body, "key")
    assert not verify_retell({"x-retell-signature": f"v={ts},d={digest.upper()}"}, body, "key")
    # Non-digit timestamp, even when correctly signed.
    assert not verify_retell(
        {"x-retell-signature": _retell_sig(body, "key", "12a")}, body, "key"
    )
    assert not verify_retell(
        {"x-retell-signature": _retell_sig(body, "key", "١٢")}, body, "key"
    )


def test_retell_max_age_rejects_future_timestamps() -> None:
    body = b"{}"
    future_ts = str(int((time.time() + 3600) * 1000))
    near_ts = str(int((time.time() + 60) * 1000))
    sig = {"x-retell-signature": _retell_sig(body, "key", future_ts)}
    assert not verify_retell(sig, body, "key", max_age=300)
    assert verify_retell(sig, body, "key", max_age=None)
    near = {"x-retell-signature": _retell_sig(body, "key", near_ts)}
    assert verify_retell(near, body, "key", max_age=300)


def test_vapi_non_ascii_header_is_rejected_not_type_error() -> None:
    assert not verify_vapi({"X-Vapi-Secret": "é"}, b"{}", "s3cr3t")
    assert not verify_vapi({"Authorization": "Bearer é"}, b"{}", "s3cr3t")
    assert verify_vapi({"X-Vapi-Secret": "sécret"}, b"{}", "sécret")
