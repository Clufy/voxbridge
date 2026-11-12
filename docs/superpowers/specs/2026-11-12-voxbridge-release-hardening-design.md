# voxbridge 0.1.0 — Release Hardening (M6) Design

Addendum to [`2026-07-06-voxbridge-design.md`](2026-07-06-voxbridge-design.md).
M1–M5 from that spec are implemented (16 tasks, 135 tests, 99% coverage). An
audit against the spec's own acceptance criteria found correctness gaps that
must close before the first PyPI upload, plus ease-of-use work needed for a
library strangers can pick up from the README alone.

## Intent

Ship a `0.1.0` that is honest (the "same code, swap provider" promise actually
holds), safe (no duplicate side effects from retries), fast to construct, and
easy to adopt (env-driven setup, a webhook + tool round trip that works without
knowing provider wire formats, runnable examples, an API reference).

PyPI is immutable per version, so everything in this addendum lands before the
`v0.1.0` tag.

## Goals

1. Close the parity gaps where one provider silently returns or drops data.
2. Make retries safe for non-idempotent requests.
3. Make `VoiceClient(...)` cheap to construct.
4. Add the ease-of-use extras chosen by the user: `from_env()` + `timeout`,
   the tool-call round trip, examples + API reference + docs deploy,
   CHANGELOG + CONTRIBUTING.
5. Make the package metadata, CI, and docs publish-ready.

## Non-goals

- Widening Python support below 3.12 (user decision: keep `>=3.12`).
- New providers (Bland etc.), pagination cursors, call update/cancel,
  phone-number management, web calls.
- Actually tagging, pushing, or uploading to PyPI. The repo has no remote; the
  release steps are documented for the user to run.

## Anti-goals

- Any silent no-op. If a provider can't do something, raise `NotSupported`.
- Retrying a request that may already have taken effect (placing a call twice).
- New runtime dependencies. Runtime deps stay `httpx` + `pydantic`.

## Decisions (user)

- Links point at `github.com/Aquib/voxbridge`.
- Python floor stays `>=3.12`; CI matrix 3.12 + 3.13.
- All four extras ship in 0.1.0.
- Vapi `create_call(from_number="+1…")` resolves the E.164 number to a Vapi
  phone-number id by lookup; anything not starting with `+` passes through as
  an id.
- Retell `update_agent` edits the agent's LLM in place.
- Retell webhooks/tool requests verify with the API key when no secret is set.
- Default branch is `main` (local `master` renamed).

## Correctness fixes

### F1 — Retell `get_agent` returns the full agent

Today it returns `system_prompt=""`, `model=""`, `first_message=None` because
those live on the Retell LLM object. Fix: after `GET /get-agent/{id}`, if
`response_engine.type == "retell-llm"`, `GET /get-retell-llm/{llm_id}` and map
both. For any other engine type (custom LLM, conversation flow) return the
agent with the prompt fields empty — the agent is real, it just isn't driven by
a prompt voxbridge can see; `raw` carries the engine block.

`Agent.raw` for Retell is the untouched agent payload plus one added key,
`raw["retell_llm"]`, holding the LLM payload whenever voxbridge fetched or
created it (builder's call: keeps the agent keys top-level, nothing lost).

**Tools map back on read (both providers, builder's call).** Vapi
`model.tools[]` entries of `type: "function"` and Retell `general_tools[]`
entries of `type: "custom"` become `Tool`s; other tool types (Retell
`end_call`, Vapi `transferCall`, …) are not modelled and stay in `raw`.
Without this a get → modify → update round trip loses tools.

### F2 — Retell `update_agent` updates everything it's given

Today it only sends `agent_name` + `voice_id` and silently drops prompt, model,
greeting, and tools — a direct violation of the no-silent-no-op rule. Fix:
`GET` the agent to find its `llm_id`, `PATCH /update-retell-llm/{llm_id}` with
the LLM fields, then `PATCH /update-agent/{id}` with name + voice; return the
merged result. If the agent's engine is not `retell-llm`, raise
`NotSupported("…prompt-driven fields require a retell-llm response engine")`.

The LLM is edited **in place** (user decision) — same as Retell's dashboard.
Agents voxbridge creates always get their own LLM; an LLM shared by hand-built
agents changes for all of them. Documented.

**Update semantics (both providers, builder's call).** `update_agent` sets the
fields voxbridge models: name, system prompt, model, voice always;
`first_message=None` and `tools=[]` mean *leave unchanged* (so tools added
outside voxbridge — Retell `end_call`, Vapi `transferCall` — survive). Clearing
the greeting or tools is not possible through voxbridge in 0.1.0; documented.
When `tools` is non-empty, voxbridge-modelled tools are replaced and
non-modelled tool types already on the agent are kept.

### F16 — Vapi `update_agent` merges into the existing model block

Vapi's PATCH replaces nested objects, so sending a fresh `model` block wipes
settings voxbridge doesn't model (temperature, `toolIds`, extra messages).
`GET /assistant/{id}`, merge voxbridge's fields into the existing `model`
block (system message replaced or inserted first; tools per the update
semantics above), then `PATCH`. Same for `voice`: provider + voiceId set,
other voice settings kept.

### F3 — Retell `create_agent` doesn't orphan the LLM

If `POST /create-agent` fails after the LLM was created, best-effort
`DELETE /delete-retell-llm/{llm_id}` and re-raise the original error. A failure
of the cleanup itself is swallowed (the original error is the one that
matters). `delete_agent` deliberately does **not** delete the LLM: an LLM can be
shared by agents created outside voxbridge.

### F4 — Retry policy that can't double-dial

Today every method, POST included, is retried once on timeouts and 5xx, so a
`create_call` whose response timed out can place a second phone call.

New policy (still one retry, max two attempts):

| Failure | Retried for |
| --- | --- |
| `httpx.ConnectError` / `httpx.ConnectTimeout` (request never sent) | any method |
| 429 (request rejected) | any method |
| read/write/pool timeout, 500/502/503/504 | idempotent requests only |

Idempotent = `GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`, `PATCH` (voxbridge's
PATCHes are full field sets), or a request explicitly marked
`idempotent=True` (Retell's read-only `POST /v3/list-calls`).

Backoff before the retry: `Retry-After` when present (seconds, or an HTTP date),
capped at 10 s; otherwise 0.5 s. A non-numeric, unparseable `Retry-After`
currently raises a bare `ValueError` out of the error path — that becomes
`retry_after=None`. Sleep goes through one module-level function so tests patch
it out.

### F5 — Lazy HTTP clients

Each `httpx.Client`/`AsyncClient` costs ~0.45 s to build on Windows (SSL
context), and every provider eagerly builds both, so `VoiceClient(...)` takes
~1 s — even for a webhook-only process that never makes a request. Build each
client on first use; `close()`/`aclose()` only close what was built.

### F6 — One voice-id format across providers

Canonical voxbridge voice spec is `"<tts-provider>:<voiceId>"`, with
`elevenlabs` normalized to `11labs` (Vapi's name). Today Retell receives the
string verbatim, so `"elevenlabs:rachel"` is rejected by Retell, whose ids look
like `retell-Cimo`, `cartesia-Cimo`, `11labs-Adrian`.

Retell's per-provider prefixes are not fully documented (verified 2026-11-12),
so the mapping is purely syntactic and round-trip safe — no prefix list:

- Retell outbound: replace the first `:` with `-` (after `elevenlabs`→`11labs`);
  a spec with no colon passes through verbatim (already a Retell id).
- Retell inbound: a `voice_id` with no `:` and at least one `-` has its first
  `-` replaced with `:` (`retell-Cimo` → `retell:Cimo`); anything else passes
  through. Outbound(inbound(x)) == x for every Retell id.
- Vapi outbound/inbound unchanged (`elevenlabs`→`11labs` already happens).

Voice *names* still differ between providers' catalogs; docs say so plainly.

### F7 — Model-provider inference

Vapi needs `model.provider`. Add `gemini*` → `google` to the existing
`gpt*`→`openai`, `claude*`→`anthropic` inference.

### F8 — Vapi `from_number` accepts a phone number

`create_call(..., from_number="+15550001111")` on Vapi: `GET /phone-number`,
find the entry whose `number` equals it, send its `id` as `phoneNumberId`. No
match → `ProviderError` naming the number. Values not starting with `+` are
treated as an id (current behaviour). The id list is fetched per call — no
cache; it's one extra GET on an already slow operation and avoids staleness.
`Call.from_number` on Vapi responses keeps reporting `phoneNumberId` (Vapi's call
object doesn't echo the number); documented.

### F10 — Retell `list_calls` reads the real v3 response (verified bug)

`POST /v3/list-calls` returns `{"items": [...], "has_more", "pagination_key"}`;
today's code reads `data["calls"]` and raises `KeyError` on every real
response (the fixture used a bare array). Read `items`; keep accepting a bare
array. v3 list items omit `transcript`, so `Call.transcript` is `None` from
`list_calls` on Retell — documented; use `get_call` for the transcript.

### F11 — `list_calls(limit=...)`

Retell returns 50 calls by default, Vapi 100, so the same call silently
returns different amounts. Add `list_calls(*, limit: int | None = None)`
(and `alist_calls`): Vapi `?limit=N`, Retell body `{"limit": N}`. No cursor
pagination in 0.1.0.

### F12 — Vapi tool-call shape (verified bug)

Vapi's `toolCallList` items are `{id, type: "function", function: {name,
arguments}}` — name/arguments are nested. Today's parser reads them at the top
level, so real tool calls normalize to `name=""`. Parse the nested shape
(arguments may be an object or a JSON string), keep the flat shape as a
fallback, and fix the doc-derived fixture to the verified shape.

### F13 — Webhook auth defaults match the official SDKs

- **Retell**: the official SDK rejects signatures older than 5 minutes by
  default. `webhook_max_age` defaults to `300` seconds (was off); pass `None`
  to disable. Passing `webhook_max_age` explicitly for Vapi raises
  `NotSupported` (Vapi's scheme has no timestamp) instead of being dropped.
- **Retell verifies by default** (user decision): Retell signs with the API
  key, so when no `webhook_secret` is given the Retell provider verifies with
  its `api_key`. `from_env` reads `RETELL_WEBHOOK_SECRET` when set, else the
  same fallback applies. Docs: use the webhook-badged key, or pass the key that
  has the badge as `webhook_secret`.
- **Vapi without a secret** still accepts unsigned requests (no secret to
  default to); docs carry a prominent warning, especially for tool endpoints.
- **Vapi**: besides the legacy `X-Vapi-Secret` header, accept the Bearer
  credential form `Authorization: Bearer <secret>`. Vapi's HMAC credential is
  not supported in 0.1.0 (documented).

### F14 — Retell `create_call` requires `from_number`

Retell's API requires `from_number`. Raise `ValueError` eagerly when it's
missing on Retell rather than sending a request that will 400.

### F15 — Retell LLM model field

Retell deprecated the LLM `model` field in favour of `model_config.primary`
(still accepted). Keep sending `model`; when reading, prefer
`model_config.primary` and fall back to `model`.

### F9 — Tests type-check

`mypy tests` currently reports 15 errors (unused ignores, union attribute
access). Fix them; CI runs `mypy src tests`.

## Extras

### E1 — `VoiceClient.from_env()` and `timeout`

```python
client = VoiceClient.from_env()                 # provider from VOICE_PROVIDER
client = VoiceClient.from_env("retell", timeout=10)
```

Reads `VOICE_PROVIDER` (when no provider argument), `<P>_API_KEY` (required —
missing raises `ValueError` naming the variable), `<P>_WEBHOOK_SECRET`
(optional), `<P>_WEBHOOK_MAX_AGE` (optional, float, Retell only). Keyword
arguments override env. No `.env` file loading (no new dependency); docs show
`python-dotenv` or the shell. `VoiceClient(..., timeout=30.0)` threads through
to `HttpCore`.

### E2 — Tool-call round trip

The `Tool` abstraction already registers once with either provider; what's
missing is the other half — receiving the invocation and replying.

- **Retell**: a custom function invocation POSTed to the tool's `url` (body
  `{"name", "args", "call"}`) parses through `parse_webhook` to `ToolCall`
  (`tool_call_id=None`, `call_id` from `call.call_id`). Same signature check as
  webhooks.
- **Vapi**: `tool-calls` message → `ToolCall` (shape fixed by F12); when a
  message carries several tool calls, the first is surfaced and the rest stay
  in `raw` — documented.
- **Reply**: `client.tool_response(event, result)` returns the JSON-ready body
  the provider expects, to be sent with HTTP 200:
  - Vapi `{"results": [{"toolCallId": id, "result": <str>}]}`. Vapi requires
    `result` to be a single-line string: non-strings are `json.dumps`-ed
    (compact), and newlines in strings are replaced with spaces.
  - Retell: the result itself (a dict stays a JSON object, which Retell can map
    to response variables; anything else is returned as-is). Retell truncates
    at 15,000 characters by default — documented, not enforced.
  - Retell's `args_at_root` tool option (body is the bare args) is not
    supported: there's no way to tell such a body from any other payload.
    Documented.

### E3 — Examples, docstrings, API reference, docs deploy

- `examples/quickstart.py` (env-driven create agent → place call),
  `examples/fastapi_server.py` (webhook endpoint + tool endpoint using
  `parse_webhook` / `tool_response`). Examples are ruff-checked, not shipped in
  the wheel.
- Docstrings on every public class and method.
- `docs/api.md` rendered by `mkdocstrings[python]`; new `docs/webhooks.md`
  (webhooks + tools guide) and `docs/configuration.md`.
- `.github/workflows/docs.yml`: build `--strict` and deploy to GitHub Pages on
  push to `main`.

### E4 — CHANGELOG + CONTRIBUTING

Keep-a-Changelog `CHANGELOG.md` with the 0.1.0 entry; `CONTRIBUTING.md` with the
dev loop (uv, tests, lint, docs) and the release checklist (create GitHub repo,
register the PyPI Trusted Publisher, push the tag).

## Publish readiness

- `pyproject.toml`: classifiers, keywords, `[project.urls]` (Homepage,
  Documentation, Source, Changelog, Issues); version single-sourced from
  `voxbridge.__version__` via hatch; sdist excludes `.superpowers/`, `.claude/`,
  `docs/superpowers/`.
- Untrack `.claude/scheduled_tasks.lock` and ignore it.
- CI: `actions/setup-python` + pip (drops the fragile `uv pip --system`
  against a uv-installed interpreter), matrix 3.12/3.13, ruff, `mypy src tests`,
  pytest with the 90% gate, `mkdocs build --strict`, `python -m build` +
  `twine check`. Runs on push to `main` and on PRs. The local `master` branch
  is renamed to `main` (user decision); docs deploy from `main`.
- README rewritten for a first-time reader: what it is, install, a 60-second
  quickstart, configuration, webhooks + tools, errors, provider matrix, links.

## Testing

Every code change is test-first with `respx` against fixtures; new fixtures are
doc-derived and marked as such. New fixtures: Retell LLM payload (exists),
Retell custom-function request, Vapi phone-number list. Parity suite gains
`get_agent` prompt round-trip and `update_agent` field coverage for both
providers. Retry-policy tests cover each row of the F4 table for sync and async.
Coverage gate stays ≥ 90%.

## Verified provider facts (2026-11-12, do not re-research)

- Retell LLM: `GET /get-retell-llm/{id}`, `PATCH /update-retell-llm/{id}`
  (`general_prompt`, `begin_message`, `general_tools`, `model` deprecated →
  `model_config.primary`), `DELETE /delete-retell-llm/{id}`.
  [docs](https://docs.retellai.com/api-references/update-retell-llm)
- Retell agent: `response_engine {type:"retell-llm", llm_id, version?}`,
  `voice_id` required. [docs](https://docs.retellai.com/api-references/create-agent)
- Retell calls: `POST /v2/create-phone-call` (`from_number`, `to_number`
  required; `override_agent_id`); `GET /v2/get-call/{id}`; `POST /v3/list-calls`
  → `{items, has_more, pagination_key?}`, body `limit` (default 50, max 1000);
  items omit transcript. [docs](https://docs.retellai.com/api-references/list-calls)
- Retell custom function: POST to tool `url`, body `{name, args, call}`,
  `X-Retell-Signature` same scheme as webhooks; any 2xx body is stringified,
  15,000-char cap. [docs](https://docs.retellai.com/build/single-multi-prompt/custom-function)
- Retell signature: `v={ts_ms},d={hex64}`, HMAC-SHA256(key=API key with
  webhook badge, msg=raw_body+ts); official SDK max age 5 min.
  [sdk](https://github.com/RetellAI/retell-python-sdk/blob/main/src/retell/lib/webhook_auth.py)
- Vapi: `GET /phone-number` bare array of `{id, number?}`, `limit`;
  `GET /call?limit=N` bare array; `toolCallList[]` = `{id, type, function:{name,
  arguments}}`; reply `{"results":[{"toolCallId","result"}]}` with a single-line
  string result, HTTP 200; server auth `X-Vapi-Secret` (legacy) or Bearer
  credential; Gemini `model.provider = "google"`.
  [tools](https://docs.vapi.ai/tools/custom-tools) ·
  [auth](https://docs.vapi.ai/server-url/server-authentication)

## Left to the builder

- Exact docstring wording, page prose, example app structure.
- How the idempotency flag is threaded through `HttpCore` (keyword argument is
  the expected shape).
