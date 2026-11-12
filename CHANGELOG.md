# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

First release, published on PyPI as `voxbridge-sdk` (import name `voxbridge`).

First release.

### Added

- `VoiceClient`, one typed facade over Vapi and Retell, with sync methods and
  `a`-prefixed async twins, selected by a provider string.
- Agent create, update, get and delete; outbound calls (`create_call`,
  `get_call`, `list_calls(limit=...)`); Pydantic `Agent`, `Call` and `Tool`
  models that keep the provider payload under `.raw`.
- Define-once `Tool` registration that maps to each provider's native tool shape,
  and `tool_response` to build the reply a provider expects for a tool call.
- Normalized webhooks: `parse_webhook` and `verify_signature` map both providers
  to one `WebhookEvent` union (`CallStarted`, `CallEnded`, `TranscriptChunk`,
  `ToolCall`, `ErrorEvent`), with per-provider signature verification.
- `VoiceClient.from_env()` reading `VOICE_PROVIDER`, `<P>_API_KEY`,
  `<P>_WEBHOOK_SECRET` and `<P>_WEBHOOK_MAX_AGE`; a `timeout` option (default 30 s).
- Error hierarchy: `VoxBridgeError`, `ProviderError` (`status_code`, `body`),
  `AuthError`, `RateLimited` (`retry_after`), `NotSupported`, `SignatureError`.
- `NotSupported` for every capability gap instead of silent no-ops.
- Retell: webhooks verified by default with the API key (or `webhook_secret`),
  with a 300 second replay window (`webhook_max_age`).
- Vapi: `Authorization: Bearer <secret>` accepted alongside `X-Vapi-Secret`;
  E.164 `from_number` resolved to a phone-number id.
- Docs site (MkDocs Material), README, configuration, webhooks and providers
  guides, runnable FastAPI and quickstart examples, CI matrix and trusted-publisher
  release workflow.

### Fixed

- Vapi tool calls now parse the real nested `function.name` / `function.arguments`
  shape (arguments as object or JSON string); previously `name` came back empty.
- Vapi `update_agent` merges onto the existing assistant instead of replacing
  settings voxbridge does not model.
- Retell `get_agent` and `update_agent` read and write the agent's LLM, so the
  prompt, greeting, model and tools are no longer dropped; `update_agent` raises
  `NotSupported` for non-`retell-llm` agents.
- Retell `create_agent` deletes the LLM it created if agent creation fails.
- Retell `list_calls` now reads the v3 `items` envelope; Retell voice ids round-trip through
  the canonical `"<tts-provider>:<voiceId>"` form (`elevenlabs` becomes `11labs`).
- Retell custom-function requests parse to `ToolCall`.
- Retell `create_call` raises `ValueError` up front when `from_number` is missing.
- Retries: only idempotent requests are retried on read/write timeouts and
  500/502/503/504 responses; connect errors, connect timeouts and 429s are retried for any
  request; `Retry-After` (seconds or HTTP date) is honoured, capped at 10 seconds.
- Passing `webhook_max_age` for Vapi raises `NotSupported` instead of being
  ignored; `from_env` rejects an unknown provider before reading other variables.
- Malformed webhook bodies raise `ProviderError` rather than a bare decode error.
- `update_agent` keeps per-tool provider settings (Vapi server secret and headers,
  Retell headers and timeouts) for tools it re-sends.
- Retell `create_agent` / `update_agent` raise `ValueError` up front for a tool
  without `endpoint_url`.
