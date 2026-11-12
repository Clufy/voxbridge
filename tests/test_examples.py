from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import pathlib
import time
from types import ModuleType
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

EXAMPLES = pathlib.Path(__file__).parent.parent / "examples"


def _load_example(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"example_{name}", EXAMPLES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _retell_sig(body: bytes, key: str) -> dict[str, str]:
    ts = str(int(time.time() * 1000))
    digest = hmac.new(key.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
    return {"x-retell-signature": f"v={ts},d={digest}"}


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VOICE_PROVIDER", "retell")
    monkeypatch.setenv("RETELL_API_KEY", "k")
    mod: Any = _load_example("fastapi_server")
    return TestClient(mod.app)


def test_fastapi_example_tool_round_trip_retell(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(
        {"name": "book_appointment", "args": {"day": "monday"}, "call": {"call_id": "c1"}}
    ).encode()
    r = _client(monkeypatch).post("/tools", content=body, headers=_retell_sig(body, "k"))
    assert r.status_code == 200
    assert r.json() == {"booked": "monday"}


def test_fastapi_example_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"name": "book_appointment", "args": {}, "call": {}}).encode()
    r = _client(monkeypatch).post("/tools", content=body, headers=_retell_sig(body, "wrong"))
    assert r.status_code == 401


def test_fastapi_example_webhook_returns_204(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"event": "call_started", "call": {"call_id": "c1"}}).encode()
    r = _client(monkeypatch).post("/webhooks", content=body, headers=_retell_sig(body, "k"))
    assert r.status_code == 204


def test_quickstart_has_no_import_side_effects() -> None:
    mod = _load_example("quickstart")
    assert callable(mod.main)
