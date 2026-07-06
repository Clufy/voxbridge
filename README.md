# voxbridge

[![CI](https://github.com/Aquib/voxbridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Aquib/voxbridge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/voxbridge.svg)](https://pypi.org/project/voxbridge/)
[![Python](https://img.shields.io/pypi/pyversions/voxbridge.svg)](https://pypi.org/project/voxbridge/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

One interface over multiple voice-agent platforms. Write your integration once
against `voxbridge`; switch between [Vapi](https://vapi.ai) and
[Retell](https://retellai.com) with a config string.

- **One API, many providers** — agents, calls, tools, and webhooks through a
  single `VoiceClient`.
- **Typed domain models** — Pydantic v2 `Agent` / `Call` / `Tool`; every model
  keeps the untouched provider payload under `.raw`.
- **Normalized webhooks** — each provider's webhook envelope maps to one
  `WebhookEvent` union, with per-provider signature verification.
- **Sync and async** — every call has an `a`-prefixed awaitable twin.
- **No silent gaps** — a capability missing on a provider raises `NotSupported`,
  never a no-op.

## Install

```bash
pip install voxbridge
```

Runtime deps: `httpx` and `pydantic` only. Requires Python 3.12+.

## Quickstart

```python
from voxbridge import VoiceClient, Agent, Tool

client = VoiceClient(provider="vapi", api_key="sk-...")  # or provider="retell"

agent = client.create_agent(Agent(
    name="Scheduler",
    system_prompt="You are a friendly scheduling assistant.",
    model="gpt-4o",
    voice="elevenlabs:rachel",
    first_message="Hi, this is Scheduler. How can I help?",
    tools=[Tool(
        name="book_appointment",
        description="Book an appointment slot",
        parameters={"type": "object", "properties": {"day": {"type": "string"}}},
        endpoint_url="https://example.com/tools/book",
    )],
))

call = client.create_call(agent.id, to_number="+15550000000")
print(call.status, call.transcript)

client.close()
```

### Async

```python
async with VoiceClient(provider="retell", api_key="sk-...") as client:
    agent = await client.acreate_agent(Agent(...))
    call = await client.aget_call("call_123")
```

### Webhooks

```python
event = client.parse_webhook(request.headers, request.body)  # verifies signature
match event:
    case CallEnded(call_id=cid, transcript=t, ended_reason=r):
        ...
    case TranscriptChunk(role=role, text=text):
        ...
```

Configure verification with `webhook_secret`; enable Retell replay protection
with `webhook_max_age` (seconds):

```python
client = VoiceClient(
    provider="retell", api_key="sk-...",
    webhook_secret="whsec_...", webhook_max_age=300,
)
```

## Vapi vs Retell

| Capability | Vapi | Retell | Notes |
| --- | --- | --- | --- |
| Agent CRUD | ✅ | ✅ | Retell create = 2 API calls (LLM + agent) |
| Outbound call | ✅ | ✅ | |
| List calls | ✅ | ✅ | |
| Transcript on call | ✅ | ✅ | Vapi `artifact.transcript`; Retell `transcript` |
| Webhook events | ✅ | ✅ | Normalized to one `WebhookEvent` union |
| Signature scheme | shared secret | HMAC-SHA256 | `X-Vapi-Secret` vs `x-retell-signature` |
| Replay protection | ⚠️ n/a | ✅ | Vapi's scheme carries no timestamp |
| Prompt location | inline (`model.messages`) | separate LLM object | voxbridge hides the difference |
| Tools | ✅ | ✅ | One `Tool` definition registers with either |
| Sync + async | ✅ | ✅ | `a`-prefixed twins |

See [docs/providers.md](docs/providers.md) for the full breakdown.

## License

[MIT](LICENSE)
