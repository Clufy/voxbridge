# voxbridge 0.1.0 Release Hardening (M6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the parity/safety gaps found in the post-M5 audit and make voxbridge publish-ready (ease of use, docs, packaging, CI).

**Architecture:** Same shape as M1–M5: pure mapping functions in `providers/_vapi_map.py` / `_retell_map.py`, thin provider adapters with sync + `a`-prefixed async twins over `HttpCore`, a `VoiceClient` facade. New behaviour goes into the pure mappers wherever possible so both sync and async paths share it.

**Tech Stack:** Python ≥3.12, Pydantic v2, httpx, pytest + respx + pytest-asyncio, ruff, mypy --strict, mkdocs-material + mkdocstrings, hatchling, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-12-voxbridge-release-hardening-design.md` (addendum to `docs/superpowers/specs/2026-07-06-voxbridge-design.md`). Read both. The "Verified provider facts" section of the addendum is authoritative — do not re-research.

## Global Constraints

- Python `>=3.12` (unchanged). Runtime deps only `httpx>=0.27`, `pydantic>=2.7`.
- `ruff check .` clean, `mypy src tests` clean (strict for src), `pytest` coverage ≥ 90%.
- All tests offline via `respx`; no live provider calls. New fixtures are hand-authored, sanitized, from the verified shapes in the spec.
- Every capability gap raises `NotSupported`; no silent no-ops.
- Every sync provider method change gets the same change on its async twin, tested.
- Commit messages: conventional commits, **no `Co-Authored-By` or "Generated with Claude" lines**.
- Run commands from the repo root with the venv: `.venv/Scripts/python -m pytest …` (Windows) / `python -m pytest …`.
- Test files keep the existing style: module-level fixture loads, `@respx.mock` decorators, typed `-> None` test functions.

## Review Focus

1. `Retry-After` header that is an HTTP date or garbage → `RateLimited.retry_after` is a float or `None`, never a bare `ValueError` (Task 1).
2. Vapi phone-number list entries without a `number` key (BYO / vapi-type numbers) → skipped during E.164 lookup, not `KeyError` (Task 3).
3. JSON `null` in newly parsed fields — `toolCallList[0].function: null`, custom-function `call: null`, `args: null`, `response_engine: null` → no crash; empty/None values (Tasks 2, 4, 5).
4. Voice ids with no separator (`"Rachel"`, `"custom_voice_abc"`) and Retell ids with several dashes (`"11labs-Adrian-v2"`) round-trip unchanged through create → get → update (Task 4).
5. Retell `update_agent` on an agent whose `response_engine` is absent or not `retell-llm` → `NotSupported`, never `KeyError`/`TypeError` (Task 5).

---

### Task 1: HttpCore — lazy clients, timeout, safe retry policy, backoff

**Files:**
- Modify: `src/voxbridge/_http.py`
- Test: `tests/test_http.py`

**Interfaces:**
- Produces:
  - `HttpCore(base_url: str, api_key: str, provider: str, *, timeout: float = 30.0)` — builds no httpx client in `__init__`.
  - `HttpCore.request(method: str, path: str, *, json: Any = None, params: Any = None, idempotent: bool | None = None) -> Any` and the same signature on `arequest`. `idempotent=None` means "decide by method".
  - Module-level `_sleep: Callable[[float], None] = time.sleep` and `_asleep: Callable[[float], Awaitable[None]] = asyncio.sleep` — tests monkeypatch these.
  - `_parse_retry_after(value: str | None) -> float | None` (seconds; numeric or HTTP date via `email.utils.parsedate_to_datetime`; negative → 0; unparseable → None).

Policy (spec F4): max 2 attempts. Retry `httpx.ConnectError`/`httpx.ConnectTimeout` and 429 for any method; retry other `httpx.TimeoutException` and 500/502/503/504 only when idempotent (`GET HEAD OPTIONS PUT DELETE PATCH`, or `idempotent=True`). Delay before retry = `min(retry_after, 10.0)` when a 429/503 carries `Retry-After`, else `0.5`. `close()`/`aclose()` close only clients that were built.

- [ ] **Step 1: Write the failing tests** (add an autouse fixture in `tests/test_http.py` that monkeypatches `voxbridge._http._sleep`/`_asleep` to record delays instead of sleeping). Tests:

```python
def test_construction_builds_no_clients():
    core = HttpCore(BASE, "k", "vapi")
    assert core._sync_client is None and core._async_client is None
    core.close()  # no-op, must not raise

@respx.mock
def test_post_not_retried_on_500():
    route = respx.post(f"{BASE}/call").mock(return_value=httpx.Response(500, json={}))
    core = HttpCore(BASE, "k", "vapi")
    with pytest.raises(ProviderError):
        core.request("POST", "/call", json={})
    assert route.call_count == 1

@respx.mock
def test_post_not_retried_on_read_timeout():
    route = respx.post(f"{BASE}/call").mock(side_effect=httpx.ReadTimeout("t"))
    with pytest.raises(ProviderError):
        HttpCore(BASE, "k", "vapi").request("POST", "/call", json={})
    assert route.call_count == 1

@respx.mock
def test_post_retried_on_connect_error():
    route = respx.post(f"{BASE}/call").mock(
        side_effect=[httpx.ConnectError("x"), httpx.Response(201, json={"id": "c"})])
    assert HttpCore(BASE, "k", "vapi").request("POST", "/call", json={}) == {"id": "c"}
    assert route.call_count == 2

@respx.mock
def test_post_retried_on_429_after_retry_after(sleeps):
    respx.post(f"{BASE}/call").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(201, json={})])
    HttpCore(BASE, "k", "vapi").request("POST", "/call", json={})
    assert sleeps == [3.0]

@respx.mock
def test_idempotent_flag_allows_post_retry_on_500():
    route = respx.post(f"{BASE}/list").mock(
        side_effect=[httpx.Response(500, json={}), httpx.Response(200, json=[])])
    HttpCore(BASE, "k", "retell").request("POST", "/list", json={}, idempotent=True)
    assert route.call_count == 2

@respx.mock
def test_get_retry_waits_default_backoff(sleeps):  # 500 then 200 → sleeps == [0.5]

@respx.mock
def test_retry_after_capped_at_10(sleeps):  # Retry-After: "120" on GET 429 → sleeps == [10.0]

@pytest.mark.parametrize("value,expected", [
    ("12", 12.0), (None, None), ("soon", None), ("-5", 0.0),
    ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0),  # date in the past → 0
])
def test_parse_retry_after(value, expected): ...

@respx.mock
def test_429_with_http_date_retry_after_does_not_crash():
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(
        429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))
    with pytest.raises(RateLimited) as ei:
        HttpCore(BASE, "k", "vapi").request("GET", "/x")
    assert ei.value.retry_after == 0.0

def test_timeout_is_applied():
    core = HttpCore(BASE, "k", "vapi", timeout=7.5)
    assert core._client().timeout == httpx.Timeout(7.5)
```

Add async twins for: POST-not-retried-on-500, POST-retried-on-connect-error, 429 backoff (asserting `_asleep` delays). Update any existing test that relied on POST retry.

- [ ] **Step 2: Run** `python -m pytest tests/test_http.py -q --no-cov` — Expected: new tests FAIL (`AttributeError: _sync_client`, call counts 2 ≠ 1).
- [ ] **Step 3: Implement** in `_http.py`: lazy `_client()` / `_aclient()` accessors creating `httpx.Client`/`AsyncClient` on first use (attributes `_sync_client`, `_async_client`, initially `None`); `_is_idempotent(method, idempotent)`; `_parse_retry_after`; one shared `_should_retry(resp_or_exc, idempotent) -> float | None` (returns delay or None) used by both loops so sync/async don't drift; `_raise` uses `_parse_retry_after`.
- [ ] **Step 4: Run** `python -m pytest -q --no-cov` — Expected: all PASS; the suite should now run markedly faster (no eager SSL setup).
- [ ] **Step 5: Commit** `git commit -am "fix: retry only idempotent requests on timeout/5xx; lazy http clients; Retry-After parsing"`

---

### Task 2: Vapi mapping — tool-call shape, tools back, update merge, gemini, tool reply

**Files:**
- Modify: `src/voxbridge/providers/_vapi_map.py`, `tests/fixtures/vapi/webhook_tool_calls.json`
- Create: `tests/fixtures/vapi/phone_numbers.json` (bare array: one `{id:"pn_sanitized000", number:"+15550000001", provider:"twilio"}`, one `{id:"pn_sanitized001", provider:"vapi"}` with no `number`)
- Test: `tests/test_vapi_map.py`, `tests/test_webhooks_parse.py`

**Interfaces:**
- Produces (all pure):
  - `vapi_to_agent(data) -> Agent` now also fills `tools` from `model.tools[]` entries with `type == "function"` (`function.name/description/parameters`, `server.url` → `endpoint_url`).
  - `merge_vapi_update(existing: dict[str, Any], agent: Agent) -> dict[str, Any]` — PATCH body per spec F16 + update semantics: `name`; `model` = existing model block with `provider`/`model` set, the first `role=="system"` message replaced (or inserted at index 0), `tools` = non-function tools kept + `agent.tools` mapped (only when `agent.tools` non-empty, else existing tools untouched); `voice` = existing voice block with `provider`/`voiceId` set; `firstMessage` only when `agent.first_message is not None`. Must not mutate `existing`.
  - `vapi_tool_response(event: ToolCall, result: Any) -> dict[str, Any]` → `{"results": [{"toolCallId": event.tool_call_id, "result": s}]}` where `s = result if isinstance(result, str) else json.dumps(result, separators=(",", ":"))`, then `\r`/`\n` replaced by spaces.
  - `find_phone_number_id(numbers: list[dict[str, Any]], e164: str) -> str | None`.
  - `_model_provider("gemini-2.5-flash") == "google"`.

- [ ] **Step 1: Fix the fixture** `webhook_tool_calls.json`: `toolCallList[0]` becomes `{"id": "toolcall_sanitized000", "type": "function", "function": {"name": "get_weather", "arguments": {"location": "San Francisco", "unit": "celsius"}}}` (verified shape). Keep `toolWithToolCallList` as is.
- [ ] **Step 2: Write the failing tests**:

```python
def test_tool_calls_nested_function_shape():  # via parse_webhook on the fixed fixture
    ev = parse_webhook(TOOL_CALLS)
    assert isinstance(ev, ToolCall)
    assert ev.name == "get_weather" and ev.arguments == {"location": "San Francisco", "unit": "celsius"}
    assert ev.tool_call_id == "toolcall_sanitized000"

def test_tool_calls_nested_string_arguments_decoded(): ...   # arguments as JSON string → dict
def test_tool_calls_flat_shape_still_supported(): ...         # {id, name, arguments} item
def test_tool_calls_null_function_does_not_crash():           # {"id": "t", "function": None} → name "", args {}

def test_vapi_to_agent_maps_function_tools_back():
    data = {**ASSISTANT, "model": {**ASSISTANT["model"], "tools": [
        {"type": "function", "function": {"name": "book", "description": "d",
         "parameters": {"type": "object"}}, "server": {"url": "https://x/t"}},
        {"type": "transferCall", "destinations": []}]}}
    a = vapi_to_agent(data)
    assert [t.name for t in a.tools] == ["book"] and a.tools[0].endpoint_url == "https://x/t"

def test_merge_update_keeps_unmodelled_model_settings():
    existing = {"model": {"provider": "openai", "model": "gpt-4o", "temperature": 0.2,
                "messages": [{"role": "system", "content": "old"}, {"role": "assistant", "content": "hi"}],
                "tools": [{"type": "transferCall"}]},
                "voice": {"provider": "11labs", "voiceId": "old", "stability": 0.5},
                "firstMessage": "keep me"}
    body = merge_vapi_update(existing, Agent(name="N", system_prompt="new", model="claude-sonnet-4",
                                             voice="openai:alloy"))
    assert body["model"]["temperature"] == 0.2
    assert body["model"]["provider"] == "anthropic"
    assert body["model"]["messages"][0] == {"role": "system", "content": "new"}
    assert body["model"]["messages"][1]["role"] == "assistant"
    assert body["model"]["tools"] == [{"type": "transferCall"}]        # tools=[] → unchanged
    assert body["voice"] == {"provider": "openai", "voiceId": "alloy", "stability": 0.5}
    assert "firstMessage" not in body                                   # None → unchanged
    assert existing["model"]["messages"][0]["content"] == "old"         # not mutated

def test_merge_update_replaces_function_tools_keeps_others(): ...
def test_merge_update_inserts_system_message_when_missing(): ...
def test_model_provider_gemini(): assert _model_provider("gemini-2.5-flash") == "google"

def test_vapi_tool_response_string_and_object():
    ev = ToolCall(name="n", tool_call_id="t1", provider="vapi")
    assert vapi_tool_response(ev, "line1\nline2") == {"results": [{"toolCallId": "t1", "result": "line1 line2"}]}
    assert vapi_tool_response(ev, {"ok": True})["results"][0]["result"] == '{"ok":true}'

def test_find_phone_number_id_skips_entries_without_number():
    assert find_phone_number_id(PHONE_NUMBERS, "+15550000001") == "pn_sanitized000"
    assert find_phone_number_id(PHONE_NUMBERS, "+19999999999") is None
```

- [ ] **Step 3: Run** `python -m pytest tests/test_vapi_map.py tests/test_webhooks_parse.py -q --no-cov` — Expected: FAIL (`ImportError: merge_vapi_update`, name `""`).
- [ ] **Step 4: Implement** the interfaces above in `_vapi_map.py`; `_first_tool_call` reads `item.get("function") or {}` before falling back to flat keys; extract `_decode_args(value) -> dict` shared by both tool-call shapes. Use `copy.deepcopy` in `merge_vapi_update`.
- [ ] **Step 5: Run** `python -m pytest -q --no-cov` — Expected: PASS.
- [ ] **Step 6: Commit** `git commit -am "fix(vapi): parse nested tool-call shape; map tools back; merge-based update body; tool reply helper"`

---

### Task 3: VapiProvider — merged update, E.164 from_number, list limit, Bearer auth, timeout, tool_response

**Files:**
- Modify: `src/voxbridge/providers/vapi.py`, `src/voxbridge/webhooks.py`
- Test: `tests/test_vapi_provider.py`, `tests/test_async.py`, `tests/test_webhooks_sig.py`

**Interfaces:**
- Consumes: Task 1 `HttpCore(..., timeout=)`, Task 2 `merge_vapi_update`, `find_phone_number_id`, `vapi_tool_response`.
- Produces:
  - `VapiProvider(api_key: str, *, webhook_secret: str | None = None, timeout: float = 30.0)`
  - `update_agent(agent_id, agent)` / `aupdate_agent`: `GET /assistant/{id}` → `PATCH /assistant/{id}` with `merge_vapi_update(existing, agent)`.
  - `create_call(agent_id, to_number, *, from_number=None)` / `acreate_call`: when `from_number` starts with `"+"`, `GET /phone-number` → `find_phone_number_id`; no match → `ProviderError(f"no Vapi phone number matches {from_number}", provider="vapi")`; otherwise pass through as `phoneNumberId`.
  - `list_calls(*, limit: int | None = None) -> list[Call]` / `alist_calls`: `GET /call` with `params={"limit": limit}` only when given.
  - `tool_response(event: ToolCall, result: Any) -> dict[str, Any]` (delegates to `vapi_tool_response`).
  - `webhooks.verify_vapi` accepts either `X-Vapi-Secret == secret` or `Authorization == f"Bearer {secret}"` (constant-time compare on both).

- [ ] **Step 1: Write the failing tests**: `test_update_agent_gets_then_patches_merged_body` (assert PATCH JSON keeps `temperature` from the GET fixture and both routes called once); `test_create_call_resolves_e164_from_number` (routes `GET /phone-number` → fixture, `POST /call`; assert request JSON `phoneNumberId == "pn_sanitized000"`); `test_create_call_unknown_e164_raises_provider_error` (and asserts `POST /call` route not called); `test_create_call_id_from_number_passes_through_without_lookup` (phone-number route `call_count == 0`); `test_list_calls_limit_sent_as_query` (`route.calls.last.request.url.params["limit"] == "5"`); `test_list_calls_no_limit_sends_no_param`; async twins of update/create_call/list limit in `tests/test_async.py`; `test_verify_vapi_bearer_header_accepted`, `test_verify_vapi_wrong_bearer_rejected` in `tests/test_webhooks_sig.py`; `test_vapi_timeout_forwarded` (`VapiProvider("k", timeout=5)._http` uses 5).
- [ ] **Step 2: Run** `python -m pytest tests/test_vapi_provider.py tests/test_async.py tests/test_webhooks_sig.py -q --no-cov` — Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above (sync and async). Update the module docstring (drop the stale "async twins are added in a later task").
- [ ] **Step 4: Run** `python -m pytest -q --no-cov` — Expected: PASS (fix older tests that mocked only the PATCH for `update_agent` by adding the GET route).
- [ ] **Step 5: Commit** `git commit -am "feat(vapi): merged update_agent, E.164 from_number lookup, list limit, Bearer webhook auth"`

---

### Task 4: Retell mapping — voice ids, LLM-aware agent mapping, tools back, v3 list, custom functions

**Files:**
- Modify: `src/voxbridge/providers/_retell_map.py`, `tests/fixtures/retell/agent.json` (`voice_id` stays `"11labs-Rachel"`)
- Create: `tests/fixtures/retell/list_calls_v3.json` (`{"items": [<call.json content minus transcript fields>], "has_more": false}`), `tests/fixtures/retell/custom_function.json` (`{"name": "book_appointment", "args": {"day": "monday"}, "call": {"call_id": "call_sanitized000", "agent_id": "agent_sanitized000", "call_status": "ongoing"}}`)
- Test: `tests/test_retell_map.py`, `tests/test_webhooks_parse.py`

**Interfaces:**
- Produces (pure):
  - `voice_to_retell(spec: str) -> str` (`"elevenlabs:Adrian"`→`"11labs-Adrian"`, `"cartesia:Cimo"`→`"cartesia-Cimo"`, `"Rachel"`→`"Rachel"`); `voice_from_retell(voice_id: str) -> str` (`"11labs-Adrian-v2"`→`"11labs:Adrian-v2"`, `"custom_voice_abc"`→unchanged, any id containing `:` → unchanged). `agent_to_retell` uses `voice_to_retell`.
  - `retell_to_agent(agent_data, llm_data=None) -> Agent`: `voice` via `voice_from_retell`; `model` = `llm_data["model_config"]["primary"]` when present else `llm_data["model"]`; `tools` from `general_tools[]` with `type == "custom"` (`url` → `endpoint_url`); `raw = {**agent_data, "retell_llm": llm_data}` when `llm_data` is not None, else `agent_data`.
  - `llm_id_of(agent_data: dict[str, Any]) -> str | None` — `response_engine.llm_id` only when `response_engine.type == "retell-llm"`; null-safe.
  - `llm_update_body(agent: Agent, existing_llm: dict[str, Any]) -> dict[str, Any]` — `general_prompt`, `model` always; `begin_message` only when `first_message is not None`; `general_tools` only when `agent.tools` non-empty, = existing non-`custom` tools + mapped `agent.tools`.
  - `retell_call_items(data: Any) -> list[dict[str, Any]]` — `data["items"]` for a dict (missing/null → `[]`), the list itself for a bare array.
  - `parse_webhook(payload)` additionally: no `event` key and `"name"` + `"args"` keys present → `ToolCall(name, arguments=args or {}, tool_call_id=None, call_id=(call or {}).get("call_id"), provider="retell", raw=payload)`.
  - `retell_tool_response(event: ToolCall, result: Any) -> Any` — returns `result` unchanged.

- [ ] **Step 1: Write the failing tests**:

```python
@pytest.mark.parametrize("spec", ["elevenlabs:Adrian", "11labs:Adrian", "cartesia:Cimo", "Rachel",
                                  "custom_voice_abc", "11labs:Adrian-v2"])
def test_voice_round_trip_is_stable(spec):
    once = voice_to_retell(spec)
    assert voice_to_retell(voice_from_retell(once)) == once

def test_voice_to_retell_examples():
    assert voice_to_retell("elevenlabs:Adrian") == "11labs-Adrian"
    assert voice_to_retell("Rachel") == "Rachel"
def test_voice_from_retell_examples():
    assert voice_from_retell("retell-Cimo") == "retell:Cimo"
    assert voice_from_retell("custom_voice_abc") == "custom_voice_abc"

def test_retell_to_agent_with_llm_keeps_llm_in_raw():
    a = retell_to_agent(AGENT, LLM)
    assert a.system_prompt == LLM["general_prompt"] and a.raw["retell_llm"] == LLM
    assert a.raw["agent_id"] == AGENT["agent_id"] and a.voice == "11labs:Rachel"

def test_model_prefers_model_config_primary():
    assert retell_to_agent(AGENT, {**LLM, "model_config": {"primary": "gpt-5"}}).model == "gpt-5"

def test_custom_tools_map_back_others_ignored(): ...  # general_tools: custom + end_call → 1 Tool
def test_llm_id_of_handles_missing_null_and_other_engines():
    assert llm_id_of(AGENT) == "llm_sanitized000"
    assert llm_id_of({**AGENT, "response_engine": None}) is None
    assert llm_id_of({**AGENT, "response_engine": {"type": "custom-llm", "llm_websocket_url": "wss://x"}}) is None
    assert llm_id_of({}) is None

def test_llm_update_body_leaves_unset_fields_out(): ...      # first_message None, tools [] → no keys
def test_llm_update_body_keeps_builtin_tools():                # existing end_call kept + new custom
def test_retell_call_items_v3_and_bare():
    assert retell_call_items(LIST_V3) == LIST_V3["items"]
    assert retell_call_items([CALL]) == [CALL]
    assert retell_call_items({"items": None}) == []

def test_custom_function_parses_to_tool_call():
    ev = parse_webhook(CUSTOM_FN)
    assert isinstance(ev, ToolCall) and ev.name == "book_appointment"
    assert ev.arguments == {"day": "monday"} and ev.call_id == "call_sanitized000"
def test_custom_function_null_args_and_call(): ...            # args None, call None → {}, None
```

- [ ] **Step 2: Run** `python -m pytest tests/test_retell_map.py tests/test_webhooks_parse.py -q --no-cov` — Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** `python -m pytest -q --no-cov` — Expected: PASS (existing tests asserting `voice == "11labs-Rachel"` from `retell_to_agent` change to `"11labs:Rachel"`; `raw` equality assertions on Retell agents with an LLM change accordingly).
- [ ] **Step 5: Commit** `git commit -am "fix(retell): canonical voice ids, LLM-aware agent mapping, v3 list items, custom-function tool calls"`

---

### Task 5: RetellProvider — full get/update, create rollback, call/list fixes, verify-by-default

**Files:**
- Modify: `src/voxbridge/providers/retell.py`
- Test: `tests/test_retell_provider.py`, `tests/test_async.py`, `tests/test_webhooks_parse.py`

**Interfaces:**
- Consumes: Task 1 `HttpCore(..., timeout=)`, `request(..., idempotent=True)`; Task 4 mappers.
- Produces:
  - `RetellProvider(api_key: str, *, webhook_secret: str | None = None, webhook_max_age: float | None = 300.0, timeout: float = 30.0)`; signature verification uses `webhook_secret if webhook_secret is not None else api_key` — so `verify_signature` never short-circuits to `True`.
  - `get_agent` / `aget_agent`: `GET /get-agent/{id}`; when `llm_id_of(...)` → `GET /get-retell-llm/{llm_id}`; return `retell_to_agent(agent, llm)`.
  - `update_agent` / `aupdate_agent`: `GET /get-agent/{id}`; `llm_id_of` is None → `NotSupported("retell agent {id} has no retell-llm response engine; prompt, model, greeting and tools can't be updated")`; else `GET /get-retell-llm/{llm_id}` → `PATCH /update-retell-llm/{llm_id}` with `llm_update_body` → `PATCH /update-agent/{id}` with `{"agent_name", "voice_id": voice_to_retell(...)}` → `retell_to_agent(updated_agent, updated_llm)`.
  - `create_agent` / `acreate_agent`: on any `VoxBridgeError` from `POST /create-agent`, best-effort `DELETE /delete-retell-llm/{llm_id}` (swallow its `VoxBridgeError`), re-raise the original.
  - `create_call` / `acreate_call`: `from_number is None` → `ValueError("Retell requires from_number for outbound calls")` before any request.
  - `list_calls(*, limit: int | None = None)` / `alist_calls`: `POST /v3/list-calls`, body `{"limit": limit}` when given else `{}`, `idempotent=True`, items via `retell_call_items`.
  - `tool_response(event: ToolCall, result: Any) -> Any` (delegates to `retell_tool_response`).

- [ ] **Step 1: Write the failing tests**: `test_get_agent_fetches_llm_and_carries_prompt` (asserts `system_prompt`, `first_message`, `model` from LLM fixture); `test_get_agent_non_llm_engine_returns_agent_without_llm_fetch` (`get-retell-llm` route `call_count == 0`); `test_update_agent_patches_llm_in_place_then_agent` (assert PATCH LLM JSON has `general_prompt`, agent PATCH JSON `voice_id == "11labs-Adrian"` for `voice="elevenlabs:Adrian"`, call order GET agent → GET llm → PATCH llm → PATCH agent via `respx.calls`); `test_update_agent_without_retell_llm_engine_raises_not_supported` (parametrize `response_engine` = `None`, absent, `{"type": "custom-llm"}`; no PATCH routes called); `test_create_agent_rolls_back_llm_when_agent_create_fails` (create-agent 400 → `ProviderError` raised, `DELETE /delete-retell-llm/llm_sanitized000` called once); `test_create_agent_rollback_failure_still_raises_original` (delete returns 500 → original 400 `ProviderError` with `status_code == 400`); `test_create_call_without_from_number_raises_value_error` (no route called); `test_list_calls_reads_v3_items_and_sends_limit` (`json.loads(route.calls.last.request.content) == {"limit": 5}`); `test_list_calls_retried_on_500` (idempotent: 500 then 200 → succeeds); `test_unsigned_webhook_rejected_by_default` (`RetellProvider("k").parse_webhook({}, body)` → `SignatureError`); `test_webhook_signed_with_api_key_accepted_by_default` (sign with `"k"` at current time); `test_default_max_age_rejects_old_signature` (timestamp 10 minutes ago → `SignatureError`); `test_max_age_none_disables_replay_check`. Async twins for get/update/create-rollback/list in `tests/test_async.py`.
- [ ] **Step 2: Update existing tests** affected by the new defaults: Retell webhook tests that sign with a fixed old timestamp pass `webhook_max_age=None` (or sign with `int(time.time()*1000)`); tests constructing `RetellProvider("k")` and parsing unsigned bodies now sign with `"k"`; `test_parity.py` Retell routes return `{"items": [...]}` for list-calls; `update_agent`/`get_agent` tests add the GET agent/LLM routes.
- [ ] **Step 3: Run** `python -m pytest tests/test_retell_provider.py tests/test_async.py tests/test_webhooks_parse.py -q --no-cov` — Expected: new tests FAIL.
- [ ] **Step 4: Implement** the interfaces above, sync and async. Update the module docstring.
- [ ] **Step 5: Run** `python -m pytest -q --no-cov` — Expected: PASS.
- [ ] **Step 6: Commit** `git commit -am "fix(retell): full get/update_agent via LLM, create rollback, v3 list, verify webhooks by default"`

---

### Task 6: VoiceClient — from_env, timeout, max_age rules, list limit, tool_response; protocol + parity

**Files:**
- Modify: `src/voxbridge/client.py`, `src/voxbridge/providers/base.py`, `.env.example`
- Test: `tests/test_client.py`, `tests/test_parity.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: Tasks 3 and 5 provider signatures.
- Produces:
  - `VoiceClient(provider: str, api_key: str, *, webhook_secret: str | None = None, webhook_max_age: float | None | _Unset = UNSET, timeout: float = 30.0)`. A module-private sentinel distinguishes "not passed". Retell: forwarded when passed (else provider default 300). Vapi: passing it (any value, incl. `None`) raises `NotSupported("webhook_max_age: Vapi webhooks carry no timestamp, so replay protection isn't available")`.
  - `VoiceClient.from_env(provider: str | None = None, *, environ: Mapping[str, str] | None = None, **overrides: Any) -> VoiceClient` (classmethod). `environ` defaults to `os.environ`. Provider = argument or `VOICE_PROVIDER` (missing → `ValueError("set VOICE_PROVIDER or pass provider=...")`). Reads `<P>_API_KEY` (missing/empty → `ValueError("<P>_API_KEY is not set")`), `<P>_WEBHOOK_SECRET`, `<P>_WEBHOOK_MAX_AGE` (float; non-numeric → `ValueError` naming the variable), `<P>` = provider upper-cased. `overrides` win over env.
  - `list_calls(*, limit: int | None = None)`, `alist_calls(*, limit=None)`; `tool_response(event: ToolCall, result: Any) -> Any`.
  - `VoiceProvider` protocol gains `list_calls(self, *, limit: int | None = None)`, `alist_calls(...)`, `tool_response(...)`; drop the stale "async twins land in Task 15" comment and the `cast` if the adapters now satisfy the protocol (keep it only if mypy needs it).
  - `.env.example` adds `RETELL_WEBHOOK_MAX_AGE=` with a comment that `RETELL_WEBHOOK_SECRET` defaults to the API key.

- [ ] **Step 1: Write the failing tests**:

```python
def test_from_env_reads_provider_key_and_secret():
    c = VoiceClient.from_env(environ={"VOICE_PROVIDER": "vapi", "VAPI_API_KEY": "k",
                                      "VAPI_WEBHOOK_SECRET": "s"})
    assert isinstance(c._provider, VapiProvider) and c._provider._webhook_secret == "s"

def test_from_env_missing_key_names_variable():
    with pytest.raises(ValueError, match="RETELL_API_KEY"):
        VoiceClient.from_env("retell", environ={})

def test_from_env_missing_provider(): ...           # ValueError mentions VOICE_PROVIDER
def test_from_env_max_age_parsed_and_bad_value_rejected(): ...   # "60" → 60.0; "soon" → ValueError naming RETELL_WEBHOOK_MAX_AGE
def test_from_env_overrides_win(): ...               # from_env("vapi", environ=..., timeout=5)

def test_vapi_with_max_age_raises_not_supported():
    with pytest.raises(NotSupported):
        VoiceClient("vapi", "k", webhook_max_age=300)

def test_retell_default_max_age_is_300(): ...         # VoiceClient("retell","k")._provider._webhook_max_age == 300
def test_list_calls_limit_delegates(): ...            # fake provider records limit
def test_tool_response_delegates(): ...
```

Parity (`tests/test_parity.py`, parametrized over both providers): `test_get_agent_parity_carries_prompt` (both return non-empty `system_prompt`, `model`, matching voice form `"<p>:<id>"`); `test_update_agent_parity` (both send the new prompt somewhere in their PATCH bodies and return an `Agent` with it); `test_tool_round_trip_parity` (Vapi tool-calls fixture and Retell custom-function fixture both parse to `ToolCall(name=…)`, and `client.tool_response(ev, {"ok": True})` returns the provider's body — Vapi `results[0].toolCallId`, Retell `{"ok": True}`).

- [ ] **Step 2: Run** `python -m pytest tests/test_client.py tests/test_parity.py tests/test_tools.py -q --no-cov` — Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above; add docstrings to every public `VoiceClient` method while here (one line + Args/Raises where non-obvious — mkdocstrings renders them in Task 8).
- [ ] **Step 4: Run** `python -m pytest -q` — Expected: PASS, coverage ≥ 90%. Then `python -m mypy src` — clean.
- [ ] **Step 5: Commit** `git commit -am "feat: VoiceClient.from_env, timeout, list limit, tool_response; parity for get/update/tools"`

---

### Task 7: Packaging, repo hygiene, CI, test type-checking

**Files:**
- Modify: `pyproject.toml`, `src/voxbridge/__init__.py`, `.gitignore`, `.github/workflows/ci.yml`, `.github/workflows/publish.yml`, `tests/test_tools.py`, `tests/test_webhooks_parse.py`, `tests/test_client.py`
- Create: `.github/workflows/docs.yml`
- Remove from index: `.claude/scheduled_tasks.lock`

**Interfaces:**
- Produces: `[project] dynamic = ["version"]` with `[tool.hatch.version] path = "src/voxbridge/__init__.py"`; `[project.urls]` Homepage/Source `https://github.com/Aquib/voxbridge`, Documentation `https://aquib.github.io/voxbridge/`, Changelog `…/blob/main/CHANGELOG.md`, Issues `…/issues`; classifiers (Development Status :: 4 - Beta, Intended Audience :: Developers, License :: OSI Approved :: MIT License, Programming Language :: Python :: 3 / 3.12 / 3.13, Topic :: Communications :: Telephony, Typing :: Typed, Framework :: AsyncIO); keywords (voice, voice-agent, vapi, retell, telephony, sdk, webhooks); `[tool.hatch.build.targets.sdist] exclude = [".superpowers", ".claude", "docs/superpowers", ".github", "uv.lock"]`; dev extras gain `build`, `twine`, `fastapi>=0.110` (examples test, Task 8); docs extras = `mkdocs-material>=9`, `mkdocstrings[python]>=0.25`.

- [ ] **Step 1: Fix the 15 `mypy tests` errors** (type the `_agent` helper in `test_tools.py` with explicit keyword params; `assert x is not None` before `.startswith`; `isinstance(ev, TranscriptChunk)` before `.role`; drop the two unused `type: ignore`s). Run `python -m mypy src tests` — Expected: `Success`.
- [ ] **Step 2: Packaging.** Apply the pyproject changes; `git rm --cached .claude/scheduled_tasks.lock`; add `.claude/scheduled_tasks.lock` to `.gitignore`. Run `python -m pip install -e ".[dev,docs]" && python -m build && python -m twine check dist/*` — Expected: `PASSED` for wheel and sdist; `python -m zipfile -l dist/*.whl` lists only `voxbridge/…` + dist-info, `tar tzf dist/*.tar.gz` shows no `.superpowers`, `.claude`, `docs/superpowers`. `python -c "import voxbridge; print(voxbridge.__version__)"` → `0.1.0`. Delete `dist/` after.
- [ ] **Step 3: CI** (`ci.yml`): triggers `push: branches: [main]`, `pull_request`, `workflow_call`; `actions/setup-python@v5` matrix `["3.12", "3.13"]` with pip cache; `pip install -e ".[dev,docs]"`; steps `ruff check .`, `mypy src tests`, `pytest --cov=voxbridge --cov-fail-under=90`, `mkdocs build --strict`, `python -m build && twine check dist/*`. `publish.yml`: keep `workflow_call` gate; build with `python -m build` via setup-python (drop uv); `environment: pypi`, `id-token: write`. `docs.yml`: on push to `main` + `workflow_dispatch`, `permissions: contents: write`, setup-python 3.12, `pip install -e ".[docs]"`, `mkdocs gh-deploy --force --strict`. Validate all three: `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml`.
- [ ] **Step 4: Run** the whole local gate: `ruff check . && mypy src tests && pytest -q` — Expected: all green.
- [ ] **Step 5: Commit** `git commit -am "build: publish-ready metadata, single-sourced version, CI matrix + docs deploy, type-checked tests"`

---

### Task 8: Docstrings, API reference, examples

**Files:**
- Modify: public docstrings in `src/voxbridge/models.py`, `events.py`, `errors.py`, `providers/vapi.py`, `providers/retell.py`, `mkdocs.yml`
- Create: `docs/api.md`, `examples/quickstart.py`, `examples/fastapi_server.py`, `examples/README.md`
- Test: `tests/test_examples.py`

**Interfaces:**
- Consumes: everything public from Tasks 1–6.
- Produces: `docs/api.md` with `::: voxbridge.VoiceClient`, `::: voxbridge.models`, `::: voxbridge.events`, `::: voxbridge.errors` (mkdocstrings, `show_source: false`, `members_order: source`); `examples/fastapi_server.py` exposing a module-level `app` (FastAPI) with `POST /webhooks` (parse → `match` on event type → 204) and `POST /tools` (parse → `ToolCall` → dispatch to a local `TOOLS: dict[str, Callable[[dict], Any]]` → `JSONResponse(client.tool_response(ev, result))`; `SignatureError` → 401; `ProviderError` → 400), client built via `VoiceClient.from_env()` lazily on first request so importing doesn't need env.

- [ ] **Step 1: Write the failing test** `tests/test_examples.py`:

```python
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

def test_fastapi_example_tool_round_trip_retell(monkeypatch):
    monkeypatch.setenv("VOICE_PROVIDER", "retell"); monkeypatch.setenv("RETELL_API_KEY", "k")
    mod = _load_example("fastapi_server")          # importlib.util.spec_from_file_location
    body = json.dumps({"name": "book_appointment", "args": {"day": "monday"},
                       "call": {"call_id": "c1"}}).encode()
    r = TestClient(mod.app).post("/tools", content=body, headers=_retell_sig(body, "k"))
    assert r.status_code == 200 and r.json() == {"booked": "monday"}

def test_fastapi_example_rejects_bad_signature(monkeypatch): ...   # → 401
def test_fastapi_example_webhook_returns_204(monkeypatch): ...     # signed call_started → 204
```

- [ ] **Step 2: Run** `python -m pytest tests/test_examples.py -q --no-cov` — Expected: FAIL (file not found).
- [ ] **Step 3: Write the examples** (`book_appointment` returns `{"booked": args["day"]}`); `examples/quickstart.py` = env-driven create agent → place call → print, guarded by `if __name__ == "__main__":`; `examples/README.md` with run commands. Docstrings on every public class/method/field in the listed modules (models: one line per field via `Field(description=...)` or class docstring Attributes section — pick one style and use it everywhere). Configure `mkdocs.yml`: `plugins: [search, mkdocstrings]` with `paths: [src]`.
- [ ] **Step 4: Run** `python -m pytest -q && ruff check . && mkdocs build --strict` — Expected: PASS, docs build with no warnings.
- [ ] **Step 5: Commit** `git commit -am "docs: public docstrings, API reference, runnable FastAPI + quickstart examples"`

---

### Task 9: README, guides, CHANGELOG, CONTRIBUTING

**Files:**
- Modify: `README.md`, `docs/index.md`, `docs/quickstart.md`, `docs/providers.md`, `mkdocs.yml` (nav)
- Create: `docs/configuration.md`, `docs/webhooks.md`, `docs/changelog.md` (`--8<-- "CHANGELOG.md"` via `pymdownx.snippets`, or a short page linking it), `CHANGELOG.md`, `CONTRIBUTING.md`

**Content requirements (every code snippet must match the final API):**
- README, for a first-time reader, in this order: one-paragraph pitch; Install; 60-second quickstart using `VoiceClient.from_env()` (plus the explicit-constructor form); Configuration table (env vars, kwargs, defaults: `timeout=30`, Retell `webhook_max_age=300`, Retell secret defaults to API key); Webhooks & tools (short FastAPI snippet with `parse_webhook` + `tool_response`, link to `examples/`); Error handling (`AuthError`, `RateLimited.retry_after`, `ProviderError.status_code/body`, `NotSupported`, `SignatureError`; retry policy in one sentence); Vapi-vs-Retell table updated (list limit, verify-by-default, Bearer, tool round trip, voice-id format, `from_number`); links to docs site, CHANGELOG, CONTRIBUTING; License. Badges keep `Aquib/voxbridge`; add a docs badge.
- `docs/webhooks.md`: verification per provider (incl. the **unsigned-Vapi warning** and the Retell webhook-badged key note), event mapping table, dedupe on `call_id`, tool round trip per provider, limitations (Vapi multi-tool messages surface the first call; Retell `args_at_root` unsupported; Retell 15,000-char result cap).
- `docs/providers.md`: matrix + "known differences" (voice ids `"<tts>:<id>"` with catalogs differing; Vapi `Call.from_number` is the phone-number id; Retell `list_calls` items have no transcript; Retell `update_agent` edits a shared LLM in place; `update_agent` can't clear greeting/tools; non-`retell-llm` Retell agents raise `NotSupported` on update).
- `docs/configuration.md`: `VoiceClient` kwargs, `from_env` variables, `.env` via `python-dotenv` or shell.
- `CHANGELOG.md` (Keep a Changelog): `## [0.1.0] - Unreleased` with Added / Fixed sections summarizing M1–M6.
- `CONTRIBUTING.md`: dev setup (`uv venv && uv pip install -e ".[dev,docs]"` and the plain-pip equivalent), the local gate command, fixture rules (doc-derived, sanitized), commit style (no AI attribution trailers), and a **Releasing** checklist: create the GitHub repo `Aquib/voxbridge` and push `main`; enable Pages (gh-pages branch); on PyPI add a Trusted Publisher (owner `Aquib`, repo `voxbridge`, workflow `publish.yml`, environment `pypi`) and create the `pypi` environment on GitHub; confirm the `voxbridge` name is free on PyPI; move CHANGELOG `Unreleased` → date; `git tag v0.1.0 && git push --tags`.

- [ ] **Step 1: Write the pages** above; add nav entries (Home, Quickstart, Configuration, Webhooks & tools, Providers, API reference, Changelog).
- [ ] **Step 2: Verify snippets** — extract every ```python block from README.md and docs/*.md into a scratch script per block and run `python -m py_compile` on each (syntax), and manually confirm each name used exists in `voxbridge.__all__` or the example. Run `mkdocs build --strict` — Expected: no warnings.
- [ ] **Step 3: Run** the full gate `ruff check . && mypy src tests && pytest -q && mkdocs build --strict` — Expected: all green.
- [ ] **Step 4: Commit** `git commit -am "docs: first-reader README, configuration/webhooks guides, CHANGELOG, CONTRIBUTING"`

---

## Self-Review

- **Spec coverage:** F1 → T4+T5; F2 → T4+T5; F3 → T5; F4 → T1; F5 → T1; F6 → T4 (Vapi unchanged); F7 → T2; F8 → T2+T3; F9 → T7; F10 → T4+T5; F11 → T3+T5+T6; F12 → T2; F13 → T3 (Bearer), T5 (Retell defaults), T6 (Vapi max_age NotSupported); F14 → T5; F15 → T4; F16 → T2+T3; tools-back + update semantics → T2/T4; E1 → T1 (timeout) + T6; E2 → T2/T4 (pure) + T3/T5 (provider) + T6 (client) + T8 (example); E3 → T6/T8 (docstrings, API ref, examples) + T7 (docs deploy); E4 → T9; publish readiness → T7; README → T9.
- **Type consistency:** `list_calls(*, limit: int | None = None)` identical in T3/T5/T6; `tool_response(event: ToolCall, result: Any)` identical in T3/T5/T6; `timeout: float = 30.0` in T1/T3/T5/T6; `webhook_max_age: float | None = 300.0` on RetellProvider (T5) and sentinel on VoiceClient (T6).
- **Review Focus:** each line has a named test in its owning task (T1 `test_parse_retry_after`/`test_429_with_http_date…`; T2 `test_find_phone_number_id_skips…`, `test_tool_calls_null_function…`; T4 `test_voice_round_trip_is_stable`, `test_custom_function_null_args_and_call`, `test_llm_id_of_handles…`; T5 `test_update_agent_without_retell_llm_engine…`).
