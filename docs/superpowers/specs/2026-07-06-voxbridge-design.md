# voxbridge — Design

A provider-agnostic Python SDK exposing one interface over multiple voice-agent
platforms (Vapi and Retell to start, extensible to Bland and others). Covers:
creating/configuring agents, placing and retrieving calls, defining tools
(function calling), and normalizing inbound webhook events into a single event
model.

Derived from `04-voicebridge-spec.md`. Package renamed from the placeholder
`voicebridge` to **`voxbridge`** (availability to be confirmed before the M5
publish).

## Goal

One `VoiceClient` that swaps providers by config, not rewrite. ComplyVoice's
`voice/` adapter imports this instead of talking to Vapi directly.

## Architecture

```
VoiceClient(provider="vapi"|"retell", api_key, webhook_secret)
   └─ selects a VoiceProvider implementation (VapiProvider | RetellProvider)
        └─ each wraps a shared httpx client (_http.py) with retry/backoff
Domain models (Pydantic v2): Agent, Call, Tool — provider extras kept under `.raw`
Events union: CallStarted | CallEnded | TranscriptChunk | ToolCall | ErrorEvent
Errors: AuthError | RateLimited | ProviderError | NotSupported
```

### Components

- **`client.py` — `VoiceClient`**: facade. Selects a provider by config-string →
  dict lookup and delegates every call. Exposes both sync and async surfaces.
- **`models.py` — `Agent`, `Call`, `Tool`**: Pydantic v2 domain models. Each
  carries `raw: dict` holding the untouched provider payload so normalization is
  never lossy.
- **`events.py` — `WebhookEvent` union**: `CallStarted`, `CallEnded`,
  `TranscriptChunk`, `ToolCall`, `ErrorEvent`. Both providers normalize to the
  same types with the same fields.
- **`providers/base.py` — `VoiceProvider` protocol**: `create_agent`,
  `update_agent`, `get_agent`, `delete_agent`, `create_call`, `get_call`,
  `list_calls`, `parse_webhook`, `verify_signature`. A `Protocol`, not an ABC —
  adapters satisfy it structurally.
- **`providers/vapi.py`, `providers/retell.py`**: adapters. Each maps the common
  shape to/from that provider's API and back into domain models.
- **`webhooks.py`**: per-provider signature verification (HMAC) helpers.
- **`errors.py`**: `AuthError`, `RateLimited`, `ProviderError`, `NotSupported`.
- **`_http.py`**: shared httpx client (sync + async), retry/backoff, error mapping.

## Key design decisions

1. **Provider = a `Protocol`.** One `VoiceClient` facade dispatches to the
   selected provider via a config-string → dict lookup. This is the one
   abstraction the library exists to provide, so it earns its keep. No plugin
   registry for a 2-entry dict.

2. **Sync + async share one core.** Each adapter builds requests and parses
   responses in shared helpers; only the httpx call differs between sync and
   async. Avoids two parallel codebases drifting.

3. **Normalization is lossy-safe.** Every model carries `raw: dict`. Capabilities
   present on one provider but not the other raise `NotSupported` — never a
   silent no-op. The provider matrix stays honest.

4. **Webhooks.** `parse_webhook(headers, raw_body)` → verify signature → return
   one `WebhookEvent`. Bad-signature and tampered-body cases tested for both
   providers.

5. **Errors normalize.** Provider HTTP failures map into the small shared
   hierarchy so callers handle `RateLimited` / `AuthError` / `ProviderError`
   uniformly regardless of provider.

## Data flow

- **Outbound (create/get/list)**: `VoiceClient` → provider adapter → `_http`
  request → provider API → response JSON → adapter maps to domain model (with
  `raw`) → returned to caller.
- **Inbound (webhooks)**: raw headers + body → `verify_signature` (reject if bad)
  → adapter maps provider payload → one `WebhookEvent` → returned to caller for
  `match`.

## Error handling

- HTTP 401/403 → `AuthError`. 429 → `RateLimited` (surface retry-after when
  present). Other 4xx/5xx → `ProviderError` with status + provider body.
- Unsupported capability on a provider → `NotSupported` (documented in the
  matrix), raised eagerly rather than silently ignored.
- Bad/absent webhook signature → signature-verification error, never a parsed
  event.

## Testing

- **Fully offline.** `respx` mocks HTTP against hand-authored, sanitized fixtures
  matching each provider's documented response shapes. Fixtures are marked as
  doc-derived so they can be swapped for real sanitized recordings later. No live
  provider account needed for CI.
- **Shared parametrized suite.** One suite runs against both adapters and asserts
  identical behavior for the shared surface (create/update/get/delete agent,
  create/get/list call, webhook normalization, tool registration).
- **Signature tests.** Valid payloads pass; tampered payloads and bad signatures
  reject — for both providers.
- **Coverage gate** ≥ 90%, `mypy --strict` clean, `ruff` clean.

## Milestones

- **M1 — Core + Vapi**: models, `VoiceProvider` protocol, `VoiceClient`, Vapi
  adapter (agent CRUD, call create/get/list), normalized errors, tests vs
  recorded Vapi fixtures.
- **M2 — Retell parity**: Retell adapter satisfying the same interface; shared
  suite asserts identical behavior for the shared surface.
- **M3 — Webhooks**: `parse_webhook` + signature verification for both;
  normalize to the `WebhookEvent` union; tests incl. bad-signature cases.
- **M4 — Tools + async**: tool/function-calling abstraction registered per
  provider; full async client mirroring the sync API.
- **M5 — Ship**: mkdocs site, ≥90% coverage gate, provider-comparison table in
  README, semver `0.1.0`, PyPI publish via OIDC, README with badges + quickstart.

- **M6 — Release hardening** (added 2026-11-12): parity/safety fixes found in the
  post-M5 audit plus ease-of-use extras, before the first PyPI upload. See
  [`2026-11-12-voxbridge-release-hardening-design.md`](2026-11-12-voxbridge-release-hardening-design.md).

## Acceptance criteria

- Same application code switches Vapi ↔ Retell by changing only `provider`.
- Webhooks from both providers normalize to identical `WebhookEvent` types with
  the same fields.
- Signature verification passes valid payloads and rejects tampered ones (both).
- A tool defined once registers correctly with either provider.
- Async and sync clients expose the same surface and are both tested.
- Entire suite runs offline via recorded fixtures; no live account needed.
- ComplyVoice's `voice/` adapter can be re-implemented on top of this without
  touching business logic.
- Coverage ≥ 90%, `mypy --strict` clean, `ruff` clean, docs published, README
  shows a Vapi-vs-Retell capability table.

## Tech stack

Python 3.12, `uv`, packaging via `hatchling`. Pydantic v2. HTTP via `httpx`
(sync + async). Tests: `pytest` + `respx`, `pytest-cov`, `ruff`, `mypy` (strict).
Docs: `mkdocs-material`. CI: GitHub Actions, PyPI publish via Trusted Publishing
(OIDC).

## Env vars (`.env.example`)

```
VOICE_PROVIDER=vapi|retell
VAPI_API_KEY=
VAPI_WEBHOOK_SECRET=
RETELL_API_KEY=
RETELL_WEBHOOK_SECRET=
```
