# Providers

voxbridge currently supports two providers, selected by the `provider` string
passed to `VoiceClient`: `"vapi"` and `"retell"`.

## Capability matrix

| Capability | Vapi | Retell | Notes |
| --- | --- | --- | --- |
| Agent create / update / get / delete | ✅ | ✅ | Retell create = 2 API calls (LLM + agent) |
| Outbound call | ✅ | ✅ | `create_call(agent_id, to_number, from_number=...)` |
| Get call / list calls | ✅ | ✅ | |
| Transcript on call | ✅ | ✅ | Vapi `artifact.transcript`; Retell `transcript` |
| Webhook events | ✅ | ✅ | Normalized to one `WebhookEvent` union |
| Signature scheme | shared secret | HMAC-SHA256 | `X-Vapi-Secret` equality vs `x-retell-signature` |
| Webhook replay protection | ⚠️ n/a | ✅ | Vapi's scheme carries no timestamp; Retell via `webhook_max_age` |
| Prompt location | inline (`model.messages`) | separate LLM object | voxbridge hides the difference |
| Tools | ✅ | ✅ | One `Tool` registers with whichever provider |
| Sync + async | ✅ | ✅ | `a`-prefixed twins |

Legend: ✅ supported · ⚠️ not applicable to this provider's protocol ·
`NotSupported` a capability requested on a provider that lacks it raises.

## What voxbridge normalizes

Both providers speak `Authorization: Bearer <key>`, but diverge past that.
voxbridge hides these differences behind the common surface:

### Vapi

- Base URL `https://api.vapi.ai`. Agents are "assistants".
- System prompt lives inline in `model.messages` as a `{role: "system"}` entry.
- Voice is `{provider, voiceId}` (voxbridge parses `"elevenlabs:rachel"`).
- Callee is `customer.number`; transcript is `artifact.transcript`.
- Webhook envelope `{"message": {"type": ...}}`; call id at `message.call.id`.
- Webhook auth is a **plain shared secret** (`X-Vapi-Secret` equality).

### Retell

- Base URL `https://api.retellai.com`, with mixed endpoint prefixes
  (`/create-agent`, `/v2/create-phone-call`, `/v3/list-calls`).
- Prompt and greeting live on a **separate Retell LLM object**; the agent
  references it via `response_engine.llm_id`. So creating an agent is two API
  calls, which voxbridge does for you.
- Callee/caller are `to_number` / `from_number`; transcript is `transcript`.
- Webhook envelope `{"event": ..., "call": {...}}`; call id at `call.call_id`.
- Webhook auth is **HMAC-SHA256** (`x-retell-signature`, format
  `v={ts},d={hex}`, digest over `raw_body + ts`).

## Webhook event mapping

Both providers' events fold into the same `WebhookEvent` union
(`CallStarted`, `CallEnded`, `TranscriptChunk`, `ToolCall`, `ErrorEvent`):

| Domain event | Vapi `message.type` | Retell `event` |
| --- | --- | --- |
| `CallStarted` | `status-update` (ringing / in-progress) | `call_started` |
| `CallEnded` | `end-of-call-report`, `status-update` (ended) | `call_ended`, `call_analyzed` |
| `TranscriptChunk` | `transcript` | `transcript_updated` |
| `ToolCall` | `tool-calls` | — |
| `ErrorEvent` | any unrecognized type | any unrecognized event |

Speaker roles are normalized: Retell's `agent` becomes `assistant` so
`TranscriptChunk.role` means the same thing across providers. Both providers may
deliver two `CallEnded`-mapped events for one call (an initial report plus an
enriched one) — dedupe on `call_id`.
