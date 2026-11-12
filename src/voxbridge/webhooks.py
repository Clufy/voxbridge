from __future__ import annotations

import hashlib
import hmac
import re
import time
from collections.abc import Mapping

_RETELL_TS = re.compile(r"[0-9]+")
_RETELL_DIGEST = re.compile(r"[0-9a-f]{64}")


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

    ``ts`` must be unix milliseconds (digits) and ``d`` 64 lowercase hex chars;
    anything else is rejected. With ``max_age`` (seconds), a timestamp more than
    ``max_age`` away from now, in either direction, is rejected. This function
    does no age check by default; the Retell provider passes its
    ``webhook_max_age`` (300 seconds unless configured otherwise).
    """
    sig = header_get(headers, "x-retell-signature")
    if not sig:
        return False
    parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
    ts, digest = parts.get("v"), parts.get("d")
    if ts is None or digest is None:
        return False
    if not _RETELL_TS.fullmatch(ts) or not _RETELL_DIGEST.fullmatch(digest):
        return False
    expected = hmac.new(secret.encode(), raw_body + ts.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), digest.encode()):
        return False
    if max_age is not None and abs(time.time() - int(ts) / 1000) > max_age:
        return False
    return True
