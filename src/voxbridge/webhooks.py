from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping


def header_get(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup."""
    lname = name.lower()
    for k, v in headers.items():
        if k.lower() == lname:
            return v
    return None


def verify_vapi(headers: Mapping[str, str], raw_body: bytes, secret: str) -> bool:
    """Vapi webhook auth: X-Vapi-Secret equals the secret, or Authorization is its Bearer form."""
    want = secret.encode()
    secret_hdr = header_get(headers, "X-Vapi-Secret")
    bearer_hdr = header_get(headers, "Authorization")
    ok_secret = secret_hdr is not None and hmac.compare_digest(secret_hdr.encode(), want)
    ok_bearer = bearer_hdr is not None and hmac.compare_digest(
        bearer_hdr.encode(), b"Bearer " + want
    )
    return ok_secret or ok_bearer


def verify_retell(
    headers: Mapping[str, str],
    raw_body: bytes,
    secret: str,
    *,
    max_age: float | None = None,
) -> bool:
    """Retell webhook auth: HMAC-SHA256 over raw_body+ts, header ``v={ts},d={hex}``.

    ponytail: age check optional, off by default — callers enable with max_age if
    replay matters. Tests stay deterministic without a clock.
    """
    sig = header_get(headers, "x-retell-signature")
    if not sig:
        return False
    parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
    ts, digest = parts.get("v"), parts.get("d")
    if not ts or not digest:
        return False
    expected = hmac.new(secret.encode(), raw_body + ts.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        return False
    if max_age is not None:
        # ts is unix millis; reject if the signature is older than max_age seconds.
        try:
            age = time.time() - int(ts) / 1000
        except ValueError:  # pragma: no cover — ts already survived HMAC over the body
            return False
        if age > max_age:
            return False
    return True
