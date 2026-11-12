# Providers

voxbridge supports two providers, selected by the `provider` string passed to
`VoiceClient`: `"vapi"` and `"retell"`.

## Capability matrix

| Capability | Vapi | Retell | Notes |
| --- | --- | --- | --- |
| Agent create / update / get / delete | yes | yes | Retell create is 2 API calls (LLM, then agent); update is 2 writes |
| Outbound call | yes | yes | `create_call(agent_id, to_number, from_number=...)`; pass a caller `from_number` on both (Retell raises `ValueError` without it) |
| Get call / list calls | yes | yes | Default list size: Vapi 100, Retell 50; pass `limit=` |
| Transcript on call | yes | yes | Retell `list_calls` items carry none; use `get_call` |
| Webhook events | yes | yes | Normalized to one `WebhookEvent` union |
| Webhook verification | optional | always | Vapi only if you set a secret |
| Signature scheme | shared secret / Bearer | HMAC-SHA256 | `X-Vapi-Secret` vs `x-retell-signature` |
| Replay protection | no | yes | Vapi's scheme has no timestamp; Retell `webhook_max_age` (300 s) |
| Tool round trip | yes | yes | `tool_response` shapes the reply per provider |
| Sync + async | yes | yes | `a`-prefixed twins for agent/call methods; webhook helpers are sync |

Anything a provider lacks raises `NotSupported`; voxbridge never no-ops silently.

## Known differences

### Voice ids

Write voices as `"<tts-provider>:<voiceId>"`, for example `"elevenlabs:rachel"` or
`"openai:alloy"`. `elevenlabs` is normalized to `11labs`. Vapi receives
`{provider, voiceId}`; Retell receives `"<provider>-<voiceId>"` (`11labs-Adrian`).
Reading an agent back returns the canonical `"<provider>:<voiceId>"` form. A bare
voice id with no colon is sent through unchanged on Retell and treated as
ElevenLabs on Vapi. The **catalogs differ**: a voice that exists on one platform
may not exist on the other, so the same string is not guaranteed to work on both.

### `Call.from_number`

On Vapi, `Call.from_number` holds the **Vapi phone-number id**, because Vapi's call
object doesn't echo the number. When you pass an E.164 `from_number` to
`create_call`, voxbridge looks it up in your Vapi phone numbers and sends the id
(`ProviderError` if none matches); a value not starting with `+` is sent as an id.
The lookup reads one page of `GET /phone-number` (Vapi's default page size), so
pass the phone-number id directly if your account has many numbers.
On Retell it is the number itself.

### Retell `list_calls` has no transcript

Items returned by Retell's list endpoint carry no transcript, so `Call.transcript`
is `None` there. Call `get_call(call_id)` for the full call.

### Retell agents are two objects

Retell keeps the prompt, greeting, model and tools on a separate LLM object that
the agent references. voxbridge handles both, with these consequences:

- **`create_agent` rollback.** If creating the agent fails after the LLM was
  created, voxbridge deletes that LLM and re-raises the original error. Caveat: if
  the create-agent request *timed out* but Retell actually created the agent, the
  rollback deletes an LLM that the live agent points to. After a timeout on
  create, check your agent list.
- **`update_agent` is two writes**, LLM first and then the agent. If the agent
  PATCH fails after the LLM PATCH succeeded, the LLM change stays; there is no
  rollback.
- **`update_agent` edits the LLM in place.** If several agents share one Retell
  LLM, updating one changes them all.
- **Non-`retell-llm` agents.** Agents whose response engine is not `retell-llm`
  (for example conversation flow) raise `NotSupported` on `update_agent`, and
  `get_agent` returns an empty prompt and model for them.

### `update_agent` semantics

`update_agent` overlays your `Agent` on the existing one and keeps provider
settings voxbridge doesn't model (voice stability, Vapi non-function tools,
Retell built-in tools such as `end_call`). Because unset means "leave alone",
`update_agent` cannot **clear** the greeting (`first_message=None`) or remove all
tools in 0.1.0. When `tools` is non-empty it sets the custom function tools to
exactly that list and keeps the built-ins. A tool whose name matches one already
on the agent keeps its provider-only settings (Vapi `server.secret`,
`server.headers`, `async`; Retell `headers`, `query_params`, `method`,
`response_variables`, `speak_*`, `timeout_ms`); voxbridge only overwrites the
name, description, parameters and URL. On Vapi, a model provider set outside
voxbridge (for example `groq`) is kept while the model name is unchanged, and
voice settings are kept while the voice provider is unchanged; switching voice
provider starts a fresh voice block.

### Retell tools need a URL

Retell calls a custom tool at its URL, so every `Tool` passed to Retell
`create_agent` / `update_agent` needs `endpoint_url`. A tool without one raises
`ValueError("Retell custom tools require endpoint_url: <name>")` before any
request is sent. On Vapi, a tool without `endpoint_url` uses the assistant's
server URL.

### Webhook authentication

Retell is verified by default; Vapi is not unless you set a secret. See
[Webhooks & tools](webhooks.md#verification).

## What voxbridge normalizes

### Vapi

- Base URL `https://api.vapi.ai`. Agents are "assistants".
- The system prompt lives inline in `model.messages` as a `system` entry.
- Callee is `customer.number`; transcript is `artifact.transcript`.
- Webhook envelope `{"message": {"type": ...}}`; call id at `message.call.id`.

### Retell

- Base URL `https://api.retellai.com`, with mixed endpoint prefixes
  (`/create-agent`, `/v2/create-phone-call`, `/v3/list-calls`).
- Prompt and greeting live on the separate LLM object referenced by
  `response_engine.llm_id`.
- Callee/caller are `to_number` / `from_number`; transcript is `transcript`.
- Webhook envelope `{"event": ..., "call": {...}}`; call id at `call.call_id`.

Both providers authenticate API requests with `Authorization: Bearer <key>`.
