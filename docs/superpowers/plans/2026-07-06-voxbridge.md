# voxbridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A provider-agnostic Python SDK (`voxbridge`) exposing one interface over Vapi and Retell for agents, calls, tools, and normalized webhook events.

**Architecture:** A `VoiceClient` facade selects a `VoiceProvider` (a `Protocol`) by config string. Adapters (`VapiProvider`, `RetellProvider`) map a common shape to/from each provider's REST API and back into Pydantic v2 domain models (`Agent`, `Call`, `Tool`), preserving unmapped fields under `.raw`. Inbound webhooks verify a per-provider signature and normalize to one `WebhookEvent` union. Sync and async share one request-building/response-parsing core.

**Tech Stack:** Python 3.12, `uv`, `hatchling`, Pydantic v2, `httpx` (sync+async), `pytest` + `respx`, `pytest-cov`, `ruff`, `mypy --strict`, `mkdocs-material`, GitHub Actions + PyPI Trusted Publishing (OIDC).

## Global Constraints

- Python `>=3.12`. Package/module name: `voxbridge`. Version `0.1.0`.
- Runtime deps only: `httpx>=0.27`, `pydantic>=2.7`. No other runtime deps.
- `mypy --strict` clean, `ruff check` clean, `pytest --cov` **≥ 90%** — all gate CI.
- All tests run **fully offline** via `respx`-mocked HTTP against committed fixtures. No test may hit a live provider API.
- Normalization is lossy-safe: every domain model carries `raw: dict[str, Any]` with the untouched provider payload.
- A capability present on one provider but absent on another raises `NotSupported` — never a silent no-op.
- Fixtures are **hand-authored from documented API shapes**, sanitized (no real keys/numbers), each with a top comment marking it doc-derived. See provider field reference in `docs/superpowers/specs/2026-07-06-voxbridge-design.md` and the verified shapes below.
- Provider verified facts (do not re-research):
  - **Vapi**: base `https://api.vapi.ai`, `Authorization: Bearer <key>`. Agents=assistants: `POST /assistant`, `GET /assistant` (bare array), `GET/PATCH/DELETE /assistant/{id}`. Calls: `POST /call`, `GET /call` (bare array), `GET/PATCH/DELETE /call/{id}`. Assistant/Call id = `id`. System prompt in `model.messages[]` `{role:"system",content}`. `voice` = `{provider, voiceId}` (e.g. `"elevenlabs:rachel"` → `{provider:"11labs", voiceId:"rachel"}`). `firstMessage`. Callee = `customer.number`. Transcript = `artifact.transcript`. Webhook envelope `{"message":{"type":...}}`, call id `message.call.id`. Webhook auth = **plain shared secret** header `X-Vapi-Secret` (equality).
  - **Retell**: base `https://api.retellai.com`, `Authorization: Bearer <key>`. Mixed prefixes: agents unversioned (`POST /create-agent`, `GET /get-agent/{id}`, `PATCH /update-agent/{id}`, `DELETE /delete-agent/{id}` (204), `GET /list-agents`); calls `POST /v2/create-phone-call`, `GET /v2/get-call/{id}`, `POST /v3/list-calls`. Agent id = `agent_id`, call id = `call_id`. Prompt/greeting on a **separate Retell LLM** (`POST /create-retell-llm` → `llm_id`), agent references `response_engine={type:"retell-llm", llm_id}`. So agent-create = 2 calls. `agent_name`, `voice_id`, `webhook_url`. Phone call: `from_number`,`to_number`. Transcript = `transcript`. Webhook envelope `{"event":..., "call":{...}}`. Webhook auth = **HMAC-SHA256** header `x-retell-signature`, format `v={ts_ms},d={hex}`, digest = HMAC-SHA256(secret=API_KEY, msg=rawBody+ts).

---

### Task 1: Project scaffold + packaging

**Files:**
- Create: `pyproject.toml`, `src/voxbridge/__init__.py`, `src/voxbridge/py.typed`, `README.md`, `LICENSE`, `.env.example`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: importable `voxbridge` package with `__version__ = "0.1.0"`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "voxbridge"
version = "0.1.0"
description = "Provider-agnostic Python SDK over Vapi, Retell, and other voice-agent platforms."
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
authors = [{ name = "Aquib" }]
dependencies = ["httpx>=0.27", "pydantic>=2.7"]

[project.optional-dependencies]
dev = ["pytest>=8", "respx>=0.21", "pytest-cov>=5", "pytest-asyncio>=0.23", "ruff>=0.5", "mypy>=1.10"]
docs = ["mkdocs-material>=9"]

[tool.hatch.build.targets.wheel]
packages = ["src/voxbridge"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "--cov=voxbridge --cov-report=term-missing"

[tool.ruff]
line-length = 100
target-version = "py312"
[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.12"
strict = true
```

- [ ] **Step 2: Write `src/voxbridge/__init__.py`**

```python
"""voxbridge: one interface over multiple voice-agent platforms."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create `src/voxbridge/py.typed`** (empty file, marks package as typed).

- [ ] **Step 4: Write `.env.example`**

```
VOICE_PROVIDER=vapi
VAPI_API_KEY=
VAPI_WEBHOOK_SECRET=
RETELL_API_KEY=
RETELL_WEBHOOK_SECRET=
```

- [ ] **Step 5: Write `tests/test_smoke.py`**

```python
import voxbridge

def test_version():
    assert voxbridge.__version__ == "0.1.0"
```

- [ ] **Step 6: Install and run**

Run: `uv venv && uv pip install -e ".[dev]" && uv run pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 7: Write `LICENSE`** (MIT, holder "Aquib") and a stub `README.md` (title + one-line description; full README in Task 16).

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "chore: project scaffold and packaging"
```

---

### Task 2: Errors

**Files:**
- Create: `src/voxbridge/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Produces: `VoxBridgeError`, `AuthError`, `RateLimited`, `ProviderError`, `NotSupported`, `SignatureError`. `ProviderError(message, *, status_code=None, provider=None, body=None)`; `RateLimited(..., retry_after=None)`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`).

Run: `uv run pytest tests/test_errors.py -v`

- [ ] **Step 3: Implement `errors.py`**

```python
from __future__ import annotations
from typing import Any

class VoxBridgeError(Exception):
    """Base for all voxbridge errors."""

class ProviderError(VoxBridgeError):
    def __init__(
        self, message: str, *, status_code: int | None = None,
        provider: str | None = None, body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.body = body

class AuthError(ProviderError):
    """401/403 from a provider."""

class RateLimited(ProviderError):
    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after

class NotSupported(VoxBridgeError):
    """Requested capability is not available on the selected provider."""

class SignatureError(VoxBridgeError):
    """Webhook signature verification failed."""
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: normalized error hierarchy"`

---

### Task 3: Domain models

**Files:**
- Create: `src/voxbridge/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces (Pydantic v2 `BaseModel`s):
  - `Tool(name: str, description: str, parameters: dict[str, Any], endpoint_url: str | None = None)`
  - `Agent(name: str, system_prompt: str, model: str, voice: str, first_message: str | None = None, tools: list[Tool] = [], id: str | None = None, raw: dict[str, Any] = {})`
  - `Call(id: str | None = None, agent_id: str | None = None, status: str | None = None, to_number: str | None = None, from_number: str | None = None, transcript: str | None = None, raw: dict[str, Any] = {})`
- All use `model_config = ConfigDict(extra="ignore")`; `raw` defaults to `{}` via `Field(default_factory=dict)`.

- [ ] **Step 1: Write the failing test**

```python
from voxbridge.models import Agent, Call, Tool

def test_agent_roundtrips_and_defaults():
    a = Agent(name="Scheduler", system_prompt="be helpful", model="gpt-4o", voice="elevenlabs:rachel")
    assert a.id is None and a.tools == [] and a.raw == {}
    dumped = a.model_dump()
    assert dumped["name"] == "Scheduler"

def test_tool_requires_schema():
    t = Tool(name="book", description="book it", parameters={"type": "object"},
             endpoint_url="https://x/y")
    assert t.parameters == {"type": "object"}

def test_raw_preserved():
    c = Call(id="c1", raw={"vendor_field": 1})
    assert c.raw["vendor_field"] == 1
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `models.py`**

```python
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class Tool(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    description: str
    parameters: dict[str, Any]
    endpoint_url: str | None = None

class Agent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    system_prompt: str
    model: str
    voice: str
    first_message: str | None = None
    tools: list[Tool] = Field(default_factory=list)
    id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

class Call(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    agent_id: str | None = None
    status: str | None = None
    to_number: str | None = None
    from_number: str | None = None
    transcript: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: Agent/Call/Tool domain models"`

---

### Task 4: Webhook events union

**Files:**
- Create: `src/voxbridge/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Produces: `CallStarted`, `CallEnded`, `TranscriptChunk`, `ToolCall`, `ErrorEvent` (Pydantic models), and `WebhookEvent = CallStarted | CallEnded | TranscriptChunk | ToolCall | ErrorEvent`.
- Common field on all: `call_id: str | None`, `provider: str`, `raw: dict[str, Any]`.
- `CallEnded` adds `transcript: str | None`, `ended_reason: str | None`.
- `TranscriptChunk` adds `role: str | None`, `text: str`.
- `ToolCall` adds `name: str`, `arguments: dict[str, Any]`, `tool_call_id: str | None`.
- `ErrorEvent` adds `message: str`.

- [ ] **Step 1: Write the failing test**

```python
from voxbridge.events import CallEnded, ToolCall, WebhookEvent

def test_call_ended_matches():
    e: WebhookEvent = CallEnded(call_id="c1", provider="vapi", transcript="hi", ended_reason="hangup", raw={})
    match e:
        case CallEnded(call_id=cid, transcript=t):
            assert cid == "c1" and t == "hi"
        case _:
            raise AssertionError

def test_tool_call_fields():
    e = ToolCall(call_id="c1", provider="retell", name="book", arguments={"day": "mon"}, tool_call_id="t1", raw={})
    assert e.name == "book" and e.arguments["day"] == "mon"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `events.py`**

```python
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")
    call_id: str | None = None
    provider: str
    raw: dict[str, Any] = Field(default_factory=dict)

class CallStarted(_Base): ...
class CallEnded(_Base):
    transcript: str | None = None
    ended_reason: str | None = None
class TranscriptChunk(_Base):
    role: str | None = None
    text: str
class ToolCall(_Base):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str | None = None
class ErrorEvent(_Base):
    message: str

WebhookEvent = CallStarted | CallEnded | TranscriptChunk | ToolCall | ErrorEvent
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: WebhookEvent union"`

---

### Task 5: Shared HTTP core + error mapping

**Files:**
- Create: `src/voxbridge/_http.py`
- Test: `tests/test_http.py`

**Interfaces:**
- Produces: `HttpCore(base_url: str, api_key: str, provider: str)` with:
  - `request(method, path, *, json=None, params=None) -> Any` (sync) and `arequest(...) -> Any` (async) — return parsed JSON (or `None` for 204).
  - Both map status → errors: 401/403→`AuthError`, 429→`RateLimited(retry_after=<Retry-After>)`, other ≥400→`ProviderError` with `body`.
  - Sends `Authorization: Bearer <api_key>`. Basic retry: retry once on 429/5xx/connect-error with fixed backoff.
  - `close()` / `aclose()`.

- [ ] **Step 1: Write the failing test** (uses `respx`)

```python
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
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `_http.py`**

```python
from __future__ import annotations
from typing import Any
import httpx
from .errors import AuthError, ProviderError, RateLimited

_RETRY_STATUS = {429, 500, 502, 503, 504}

class HttpCore:
    def __init__(self, base_url: str, api_key: str, provider: str, *, timeout: float = 30.0) -> None:
        self.provider = provider
        headers = {"Authorization": f"Bearer {api_key}"}
        self._sync = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
        self._async = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)

    def _raise(self, resp: httpx.Response) -> None:
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
        msg = f"{self.provider} {resp.status_code}"
        if resp.status_code in (401, 403):
            raise AuthError(msg, status_code=resp.status_code, provider=self.provider, body=body)
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            raise RateLimited(msg, status_code=429, provider=self.provider, body=body,
                              retry_after=float(ra) if ra else None)
        raise ProviderError(msg, status_code=resp.status_code, provider=self.provider, body=body)

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def request(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        for attempt in (1, 2):
            resp = self._sync.request(method, path, json=json, params=params)
            if resp.status_code < 400:
                return self._parse(resp)
            if resp.status_code in _RETRY_STATUS and attempt == 1:
                continue
            self._raise(resp)
        self._raise(resp)  # pragma: no cover

    async def arequest(self, method: str, path: str, *, json: Any = None, params: Any = None) -> Any:
        for attempt in (1, 2):
            resp = await self._async.request(method, path, json=json, params=params)
            if resp.status_code < 400:
                return self._parse(resp)
            if resp.status_code in _RETRY_STATUS and attempt == 1:
                continue
            self._raise(resp)
        self._raise(resp)  # pragma: no cover

    def close(self) -> None:
        self._sync.close()

    async def aclose(self) -> None:
        await self._async.aclose()
```

Note: ponytail — retry is a fixed one-shot, not exponential/jittered. Comment it: `# ponytail: single retry, no backoff jitter; add tenacity if flakiness demands it`.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: shared httpx core with error mapping and retry"`

---

### Task 6: VoiceProvider protocol

**Files:**
- Create: `src/voxbridge/providers/__init__.py` (empty), `src/voxbridge/providers/base.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Produces: `VoiceProvider` — a `typing.Protocol` (runtime_checkable) with methods:
  - `create_agent(agent: Agent) -> Agent`, `update_agent(agent_id: str, agent: Agent) -> Agent`, `get_agent(agent_id: str) -> Agent`, `delete_agent(agent_id: str) -> None`
  - `create_call(agent_id: str, to_number: str, *, from_number: str | None = None) -> Call`, `get_call(call_id: str) -> Call`, `list_calls() -> list[Call]`
  - `parse_webhook(headers: Mapping[str, str], raw_body: bytes) -> WebhookEvent`, `verify_signature(headers: Mapping[str, str], raw_body: bytes) -> bool`
  - async twins prefixed `a` (e.g. `acreate_agent`) — Task 15 relies on these existing in the protocol.
  - `close() -> None`, `aclose() -> None`.

- [ ] **Step 1: Write the failing test**

```python
from voxbridge.providers.base import VoiceProvider

def test_protocol_is_runtime_checkable():
    class Dummy:
        pass
    assert not isinstance(Dummy(), VoiceProvider)

def test_protocol_lists_expected_methods():
    for m in ("create_agent", "get_call", "parse_webhook", "verify_signature", "acreate_agent"):
        assert hasattr(VoiceProvider, m)
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `providers/base.py`** — a `@runtime_checkable` `Protocol` declaring every method above with the signatures from the Interfaces block (bodies are `...`). Include the async twins and `close`/`aclose`.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: VoiceProvider protocol"`

---

### Task 7: Vapi mapping helpers (pure functions)

**Files:**
- Create: `src/voxbridge/providers/_vapi_map.py`
- Test: `tests/test_vapi_map.py`
- Create fixtures: `tests/fixtures/vapi/assistant.json`, `tests/fixtures/vapi/call.json`

**Interfaces:**
- Produces pure functions (no I/O, easy to test):
  - `agent_to_vapi(agent: Agent) -> dict` — maps to CreateAssistantDTO: `name`, `firstMessage`, `model={provider,model,messages:[{role:"system",content:system_prompt}]}`, `voice=_voice(agent.voice)`.
  - `vapi_to_agent(data: dict) -> Agent` — pulls `id`, `name`, `firstMessage`, system prompt out of `model.messages`, voice back to `"provider:voiceId"`; whole `data` under `raw`.
  - `_voice(spec: str) -> dict` — `"elevenlabs:rachel"` → `{"provider": "11labs", "voiceId": "rachel"}`; bare string → `{"provider":"11labs","voiceId": spec}`.
  - `vapi_to_call(data: dict) -> Call` — `id`, `status`, `customer.number`→`to_number`, `phoneNumberId`-derived `from_number` if present, `artifact.transcript`→`transcript`, `raw=data`.
  - `call_request(agent_id, to_number, from_number) -> dict` — `{assistantId, customer:{number:to_number}}` (+ `phoneNumberId` if from_number given).

- [ ] **Step 1: Author fixtures.** `tests/fixtures/vapi/assistant.json` — a sanitized Assistant with `id`, `name`, `model.messages` containing a system message, `voice={provider:"11labs",voiceId:"rachel"}`, `firstMessage`. `tests/fixtures/vapi/call.json` — a Call with `id`, `status:"ended"`, `customer.number:"+15550000000"`, `artifact.transcript:"Agent: hi..."`. Top of each: a JSON is not commentable, so add a sibling `tests/fixtures/README.md` stating all fixtures are hand-authored from documented shapes and sanitized.

- [ ] **Step 2: Write the failing test**

```python
import json, pathlib
from voxbridge.models import Agent
from voxbridge.providers._vapi_map import (
    agent_to_vapi, vapi_to_agent, vapi_to_call, call_request, _voice,
)

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"

def test_voice_parsing():
    assert _voice("elevenlabs:rachel") == {"provider": "11labs", "voiceId": "rachel"}

def test_agent_to_vapi_puts_prompt_in_messages():
    a = Agent(name="S", system_prompt="be nice", model="gpt-4o", voice="elevenlabs:rachel", first_message="hi")
    out = agent_to_vapi(a)
    assert out["firstMessage"] == "hi"
    assert out["model"]["messages"][0] == {"role": "system", "content": "be nice"}

def test_vapi_to_agent_reads_prompt_and_preserves_raw():
    data = json.loads((FX / "assistant.json").read_text())
    a = vapi_to_agent(data)
    assert a.id == data["id"]
    assert a.system_prompt  # extracted from model.messages
    assert a.raw == data

def test_vapi_to_call_reads_transcript_and_number():
    data = json.loads((FX / "call.json").read_text())
    c = vapi_to_call(data)
    assert c.id == data["id"]
    assert c.to_number == "+15550000000"
    assert c.transcript == data["artifact"]["transcript"]
```

- [ ] **Step 3: Run — expect FAIL.**

- [ ] **Step 4: Implement `_vapi_map.py`** per the Interfaces block. For `model.model`: pass `agent.model` through as the model id and default `provider` by prefix (`gpt`→`openai`, `claude`→`anthropic`, else `openai`). Extract system prompt = first `model.messages` item with `role=="system"` (empty string if absent).

- [ ] **Step 5: Run — expect PASS.**

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: Vapi mapping helpers + fixtures"`

---

### Task 8: VapiProvider (sync agent + call CRUD)

**Files:**
- Create: `src/voxbridge/providers/vapi.py`
- Test: `tests/test_vapi_provider.py`

**Interfaces:**
- Consumes: `HttpCore` (Task 5), Vapi maps (Task 7), models, errors.
- Produces: `VapiProvider(api_key: str, *, webhook_secret: str | None = None)` implementing the sync `VoiceProvider` surface for agents/calls (webhooks in Task 11). Uses `HttpCore("https://api.vapi.ai", api_key, "vapi")`.

- [ ] **Step 1: Write the failing test** (respx against fixtures)

```python
import json, pathlib, httpx, respx
from voxbridge.models import Agent
from voxbridge.providers.vapi import VapiProvider

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
ASSISTANT = json.loads((FX / "assistant.json").read_text())
CALL = json.loads((FX / "call.json").read_text())

@respx.mock
def test_create_agent():
    respx.post("https://api.vapi.ai/assistant").mock(return_value=httpx.Response(201, json=ASSISTANT))
    p = VapiProvider("k")
    a = p.create_agent(Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel"))
    assert a.id == ASSISTANT["id"]
    p.close()

@respx.mock
def test_get_and_list_call():
    respx.get(f"https://api.vapi.ai/call/{CALL['id']}").mock(return_value=httpx.Response(200, json=CALL))
    respx.get("https://api.vapi.ai/call").mock(return_value=httpx.Response(200, json=[CALL]))
    p = VapiProvider("k")
    assert p.get_call(CALL["id"]).transcript == CALL["artifact"]["transcript"]
    assert len(p.list_calls()) == 1
    p.close()

@respx.mock
def test_delete_agent():
    respx.delete("https://api.vapi.ai/assistant/a1").mock(return_value=httpx.Response(200, json=ASSISTANT))
    p = VapiProvider("k")
    assert p.delete_agent("a1") is None
    p.close()
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `vapi.py`** — each method calls `self._http.request(...)` then maps via Task 7 functions. `create_call` posts `call_request(...)` and returns `vapi_to_call`. `list_calls` maps the bare array.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: VapiProvider agent + call CRUD (sync)"`

---

### Task 9: VoiceClient facade

**Files:**
- Create: `src/voxbridge/client.py`; Modify: `src/voxbridge/__init__.py` (export public API)
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: providers, models, errors.
- Produces: `VoiceClient(provider: str, api_key: str, *, webhook_secret: str | None = None)` delegating every `VoiceProvider` method to the selected adapter via a `{"vapi": VapiProvider, "retell": RetellProvider}` dict (Retell registered in Task 13). Unknown provider → `ValueError`. Supports context-manager (`__enter__/__exit__` → `close`, `__aenter__/__aexit__` → `aclose`).
- `__init__.py` exports: `VoiceClient, Agent, Call, Tool`, all events, all errors.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from voxbridge import VoiceClient

def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        VoiceClient(provider="nope", api_key="k")

def test_selects_vapi(monkeypatch):
    c = VoiceClient(provider="vapi", api_key="k")
    assert type(c._provider).__name__ == "VapiProvider"
    c.close()
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `client.py`** — dict lookup, delegate methods (`create_agent`, `update_agent`, `get_agent`, `delete_agent`, `create_call`, `get_call`, `list_calls`, `parse_webhook`, `verify_signature`, and async twins), context managers. Update `__init__.py` exports.

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: VoiceClient facade"`

**M1 checkpoint:** `uv run pytest && uv run mypy src && uv run ruff check .` all green.

---

### Task 10: Retell mapping helpers + RetellProvider (sync)

**Files:**
- Create: `src/voxbridge/providers/_retell_map.py`, `src/voxbridge/providers/retell.py`
- Test: `tests/test_retell_map.py`, `tests/test_retell_provider.py`
- Fixtures: `tests/fixtures/retell/agent.json`, `tests/fixtures/retell/llm.json`, `tests/fixtures/retell/call.json`

**Interfaces:**
- Consumes: `HttpCore`, models, errors.
- Produces:
  - `_retell_map`: `agent_to_llm(agent) -> dict` (`{general_prompt, begin_message, model}`), `agent_to_retell(agent, llm_id) -> dict` (`{response_engine:{type:"retell-llm",llm_id}, voice_id, agent_name}`), `retell_to_agent(agent_data, llm_data=None) -> Agent`, `retell_to_call(data) -> Call`, `phone_call_request(agent_id, to_number, from_number) -> dict`.
  - `RetellProvider(api_key, *, webhook_secret=None)` — base `https://api.retellai.com`. `create_agent` = **two calls**: `POST /create-retell-llm` then `POST /create-agent` (handles the mixed prefixes and the LLM/agent split). `get_agent` → `GET /get-agent/{id}`. `delete_agent` → `DELETE /delete-agent/{id}` (204). `create_call` → `POST /v2/create-phone-call`. `get_call` → `GET /v2/get-call/{id}`. `list_calls` → `POST /v3/list-calls` (body `{}`), returns the array (handle `{"calls":[...]}` or bare list).

- [ ] **Step 1: Author fixtures** (sanitized): `llm.json` with `llm_id`, `general_prompt`, `begin_message`; `agent.json` with `agent_id`, `agent_name`, `voice_id`, `response_engine`; `call.json` with `call_id`, `call_status:"ended"`, `from_number`, `to_number`, `transcript`.

- [ ] **Step 2: Write failing tests** — map tests (prompt goes to LLM body, agent references llm_id, call transcript/number extracted, raw preserved) and provider tests (respx: `create_agent` mocks both `/create-retell-llm` and `/create-agent`; `get_call` mocks `/v2/get-call/{id}`; `delete_agent` mocks 204; `list_calls` mocks `/v3/list-calls`). Mirror the Vapi test shapes in Tasks 7–8.

```python
@respx.mock
def test_create_agent_makes_two_calls():
    respx.post("https://api.retellai.com/create-retell-llm").mock(
        return_value=httpx.Response(201, json=LLM))
    respx.post("https://api.retellai.com/create-agent").mock(
        return_value=httpx.Response(201, json=AGENT))
    p = RetellProvider("k")
    a = p.create_agent(Agent(name="S", system_prompt="x", model="gpt-4.1", voice="v1"))
    assert a.id == AGENT["agent_id"]
    p.close()
```

- [ ] **Step 3: Run — expect FAIL. Step 4: Implement. Step 5: Run — expect PASS.**

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: RetellProvider agent + call CRUD (sync)"`

---

### Task 11: Register Retell + shared parity suite

**Files:**
- Modify: `src/voxbridge/client.py` (add `"retell"` to registry)
- Test: `tests/test_parity.py`

**Interfaces:**
- Consumes: both providers.
- Produces: a `pytest.mark.parametrize`d suite over `("vapi", "retell")` asserting identical behavior for the shared surface (create agent → returns `Agent` with `id`; get_call → `Call` with `transcript`; list_calls → `list[Call]`). Each param sets up the right respx routes and fixtures for that provider.

- [ ] **Step 1: Write the parametrized parity test** (one test body, provider-specific route setup via a small helper/fixture). Assert the *returned domain types and populated fields* match across providers — not the wire payloads.

- [ ] **Step 2: Run — expect FAIL** (retell not registered). **Step 3: Register retell in client. Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: register Retell + cross-provider parity suite"`

**M2 checkpoint:** parity suite green for both providers.

---

### Task 12: Webhook signature verification

**Files:**
- Create: `src/voxbridge/webhooks.py`
- Test: `tests/test_webhooks_sig.py`

**Interfaces:**
- Produces:
  - `verify_vapi(headers, raw_body, secret) -> bool` — `hmac.compare_digest(headers.get("X-Vapi-Secret",""), secret)` (case-insensitive header lookup).
  - `verify_retell(headers, raw_body, secret) -> bool` — parse `x-retell-signature` value `v={ts},d={hex}`; recompute `hmac.new(secret, raw_body + str(ts).encode(), sha256).hexdigest()`; `compare_digest`; reject if `ts` older than 5 min is out of scope for the unit (no clock in tests) — verify digest only, and expose `max_age` param defaulting to `None` (skip age check) so tests are deterministic. `# ponytail: age check optional, off by default — callers enable with max_age if replay matters`.
  - `header_get(headers, name) -> str | None` case-insensitive helper.

- [ ] **Step 1: Write the failing test**

```python
import hmac, hashlib
from voxbridge.webhooks import verify_vapi, verify_retell

def test_vapi_shared_secret():
    assert verify_vapi({"X-Vapi-Secret": "s3cr3t"}, b"{}", "s3cr3t")
    assert not verify_vapi({"X-Vapi-Secret": "wrong"}, b"{}", "s3cr3t")

def test_retell_hmac_roundtrip():
    secret, body, ts = "key", b'{"event":"call_ended"}', "1720000000000"
    digest = hmac.new(secret.encode(), body + ts.encode(), hashlib.sha256).hexdigest()
    sig = f"v={ts},d={digest}"
    assert verify_retell({"x-retell-signature": sig}, body, secret)
    assert not verify_retell({"x-retell-signature": f"v={ts},d=deadbeef"}, body, secret)
```

- [ ] **Step 2: Run — expect FAIL. Step 3: Implement `webhooks.py`. Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: per-provider webhook signature verification"`

---

### Task 13: parse_webhook normalization (both providers)

**Files:**
- Modify: `src/voxbridge/providers/vapi.py`, `src/voxbridge/providers/retell.py`
- Test: `tests/test_webhooks_parse.py`
- Fixtures: `tests/fixtures/vapi/webhook_call_ended.json`, `webhook_tool_calls.json`, `webhook_transcript.json`; `tests/fixtures/retell/webhook_call_started.json`, `webhook_call_ended.json`, `webhook_transcript.json`

**Interfaces:**
- Consumes: events (Task 4), webhooks (Task 12).
- Produces: `VapiProvider.parse_webhook(headers, raw_body)` and `RetellProvider.parse_webhook(...)`:
  - verify signature first → raise `SignatureError` if secret configured and verification fails.
  - map Vapi `message.type`: `status-update`(status=="ended")/`end-of-call-report`→`CallEnded`, first `status-update`(ringing/in-progress) → `CallStarted`, `transcript`→`TranscriptChunk`, `tool-calls`→`ToolCall` (from `toolCallList[0]`), else `ErrorEvent`/generic. Map Retell `event`: `call_started`→`CallStarted`, `call_ended`/`call_analyzed`→`CallEnded`, `transcript_updated`→`TranscriptChunk`.
  - `verify_signature(headers, raw_body) -> bool` delegates to the Task 12 function with the provider's `webhook_secret`.

- [ ] **Step 1: Author webhook fixtures** matching the verified envelopes (`{"message":{"type":...}}` for Vapi, `{"event":...,"call":{...}}` for Retell), sanitized.

- [ ] **Step 2: Write failing tests** — for each provider, a valid signed body normalizes to the expected `WebhookEvent` subtype with the expected `call_id`/fields; a tampered body (bad signature) raises `SignatureError`; both providers' `CallEnded` expose the same field names.

```python
def test_both_providers_call_ended_same_shape(vapi_signed, retell_signed):
    ev_v = vapi_provider.parse_webhook(*vapi_signed)
    ev_r = retell_provider.parse_webhook(*retell_signed)
    assert type(ev_v) is type(ev_r) is CallEnded
    assert set(ev_v.model_dump()) == set(ev_r.model_dump())

def test_tampered_vapi_rejected(vapi_signed):
    headers, body = vapi_signed
    with pytest.raises(SignatureError):
        vapi_provider.parse_webhook(headers, body + b"tampered")
```

- [ ] **Step 3: Run — expect FAIL. Step 4: Implement parse_webhook in both adapters. Step 5: Run — expect PASS.**

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: webhook normalization for both providers"`

**M3 checkpoint:** webhooks normalize identically; bad signatures rejected for both.

---

### Task 14: Tool registration per provider

**Files:**
- Modify: `src/voxbridge/providers/_vapi_map.py`, `src/voxbridge/providers/_retell_map.py` (fold tools into agent bodies)
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `Tool` model.
- Produces: `agent_to_vapi` includes `model.tools=[{type:"function", function:{name,description,parameters}, server:{url:endpoint_url}}]` for each `agent.tools`. `agent_to_llm` (Retell) includes `general_tools=[{type:"custom", name, description, ... , url:endpoint_url, parameters}]`. A tool defined once on `Agent.tools` registers with whichever provider. Capabilities with no provider mapping raise `NotSupported`.

- [ ] **Step 1: Write the failing test**

```python
from voxbridge.models import Agent, Tool
from voxbridge.providers._vapi_map import agent_to_vapi
from voxbridge.providers._retell_map import agent_to_llm

TOOL = Tool(name="book", description="book it", parameters={"type": "object"}, endpoint_url="https://x/y")

def test_tool_registers_with_vapi():
    body = agent_to_vapi(Agent(name="S", system_prompt="x", model="gpt-4o", voice="v", tools=[TOOL]))
    fn = body["model"]["tools"][0]
    assert fn["function"]["name"] == "book"
    assert fn["server"]["url"] == "https://x/y"

def test_tool_registers_with_retell():
    body = agent_to_llm(Agent(name="S", system_prompt="x", model="gpt-4.1", voice="v", tools=[TOOL]))
    assert body["general_tools"][0]["name"] == "book"
```

- [ ] **Step 2: Run — expect FAIL. Step 3: Implement. Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: define-once tool registration for both providers"`

---

### Task 15: Async client surface

**Files:**
- Modify: `src/voxbridge/providers/vapi.py`, `retell.py` (add `a*` methods), `src/voxbridge/client.py` (delegate async)
- Test: `tests/test_async.py`

**Interfaces:**
- Consumes: `HttpCore.arequest` (already built).
- Produces: `acreate_agent`, `aupdate_agent`, `aget_agent`, `adelete_agent`, `acreate_call`, `aget_call`, `alist_calls` on both providers and on `VoiceClient` — same signatures as sync, awaitable, sharing the same mapping helpers (only the HTTP call differs). `parse_webhook`/`verify_signature` stay sync (no I/O).

- [ ] **Step 1: Write the failing test** (respx works for async too)

```python
import json, pathlib, httpx, respx
from voxbridge import VoiceClient
from voxbridge.models import Agent

FX = pathlib.Path(__file__).parent / "fixtures" / "vapi"
ASSISTANT = json.loads((FX / "assistant.json").read_text())

@respx.mock
async def test_async_create_agent_matches_sync():
    respx.post("https://api.vapi.ai/assistant").mock(return_value=httpx.Response(201, json=ASSISTANT))
    async with VoiceClient(provider="vapi", api_key="k") as c:
        a = await c.acreate_agent(Agent(name="S", system_prompt="x", model="gpt-4o", voice="elevenlabs:rachel"))
    assert a.id == ASSISTANT["id"]

def test_async_surface_mirrors_sync():
    from voxbridge.providers.vapi import VapiProvider
    for m in ("create_agent", "get_call", "list_calls"):
        assert hasattr(VapiProvider, m) and hasattr(VapiProvider, "a" + m)
```

- [ ] **Step 2: Run — expect FAIL. Step 3: Implement `a*` methods (reuse the pure mapping functions; call `arequest`). Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: async client surface mirroring sync"`

**M4 checkpoint:** tools + async both green; sync and async expose the same surface.

---

### Task 16: Docs, README, CI, coverage gate — ship

**Files:**
- Create: `mkdocs.yml`, `docs/index.md`, `docs/providers.md` (capability table), `docs/quickstart.md`, `.github/workflows/ci.yml`, `.github/workflows/publish.yml`
- Modify: `README.md` (badges, quickstart, Vapi-vs-Retell table)
- Test: (coverage gate enforced in CI; add any tests needed to reach ≥90%)

**Interfaces:**
- Produces: mkdocs-material site; README with a capability matrix; CI running `ruff`, `mypy --strict`, `pytest --cov --cov-fail-under=90`; publish workflow using PyPI Trusted Publishing (OIDC, `id-token: write`, no token secret).

- [ ] **Step 1: Coverage audit.** Run `uv run pytest --cov --cov-report=term-missing`. For each file under 90%, add a focused test (e.g. error paths in `_http`, `update_agent`, async `alist_calls`, `NotSupported` raise). Do not add tests that assert nothing.

- [ ] **Step 2: Write the Vapi-vs-Retell capability table** in `README.md` and `docs/providers.md` — columns: Capability | Vapi | Retell | Notes. Rows: agent CRUD, outbound call, list calls, transcript on call, webhook events, signature scheme (shared-secret vs HMAC), prompt location (inline vs separate LLM), tools. Mark honest gaps (✅/⚠️/`NotSupported`).

- [ ] **Step 3: Write `mkdocs.yml`** (material theme, nav: index/quickstart/providers) and the three docs pages. `docs/quickstart.md` = the spec's Public-API snippet, runnable-shaped.

- [ ] **Step 4: Write `.github/workflows/ci.yml`** — matrix py3.12, `uv sync`, run ruff + mypy --strict + pytest with `--cov-fail-under=90`.

- [ ] **Step 5: Write `.github/workflows/publish.yml`** — on tag `v*`, build with hatchling, publish via `pypa/gh-action-pypi-publish` with `permissions: id-token: write` (Trusted Publishing, no API token).

- [ ] **Step 6: Add README badges** (CI status, PyPI version, python versions, license). Verify `README` renders the capability table.

- [ ] **Step 7: Final gate.** Run `uv run pytest --cov --cov-fail-under=90 && uv run mypy --strict src && uv run ruff check . && uv run mkdocs build`. All must pass.

- [ ] **Step 8: Commit** `git add -A && git commit -m "docs: mkdocs site, README capability table, CI + OIDC publish"`

**M5 checkpoint:** coverage ≥90%, mypy/ruff clean, docs build, capability table present. Tag `v0.1.0` only after the user confirms the PyPI name is free.

---

## Self-Review

**Spec coverage:**
- Unified client → Task 9. Domain models → Task 3. Events union → Task 4. Adapters/protocol → Tasks 6,8,10. Agent mgmt (create/update/get/delete) → Tasks 8,10. Call mgmt (create/get/list) → Tasks 8,10. Tools → Task 14. Webhook normalization + per-provider signature → Tasks 12,13. Sync+async → Task 15. Errors hierarchy → Task 2. `raw` preservation → Task 3 + every map. `NotSupported` for capability gaps → Tasks 2,14. Offline fixtures → Tasks 7,10,13. Parity suite → Task 11. Ship (docs/CI/coverage/OIDC/table) → Task 16. All acceptance criteria mapped.

**Placeholder scan:** No "TBD/handle edge cases/similar to". Tasks 10 and 13 reference "mirror the Vapi test shapes" but give the distinctive new test code (two-call create, tampered-body reject) inline — the mechanical CRUD mirrors are unambiguous given Tasks 7–8 are complete.

**Type consistency:** `Agent`/`Call`/`Tool` fields consistent across all map functions. `HttpCore.request/arequest` names match usage. Provider method names match the protocol (Task 6) and the client delegation (Task 9). Async twins named `a<method>` consistently in Tasks 6, 9, 15. `verify_vapi`/`verify_retell` names consistent Tasks 12–13.

**Scope:** One library, one coherent artifact — a single plan is right; milestones give natural review checkpoints (M1–M5).
