# voxbridge

[![CI](https://github.com/Aquib/voxbridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Aquib/voxbridge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/voxbridge.svg)](https://pypi.org/project/voxbridge/)
[![Python](https://img.shields.io/pypi/pyversions/voxbridge.svg)](https://pypi.org/project/voxbridge/)
[![Docs](https://img.shields.io/badge/docs-aquib.github.io%2Fvoxbridge-blue.svg)](https://aquib.github.io/voxbridge/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Aquib/voxbridge/blob/main/LICENSE)

voxbridge is a Python SDK that puts one typed `VoiceClient` over the
[Vapi](https://vapi.ai) and [Retell](https://retellai.com) voice-agent
platforms. Create agents, place outbound calls, verify and parse webhooks, and
answer tool calls with the same code on either provider; switching is a config
string. Both sync and async are supported, every model keeps the untouched
provider payload under `.raw`, and a capability a provider lacks raises
`NotSupported` instead of silently doing nothing.

## Install

```bash
pip install voxbridge
```

Requires Python 3.12+. Runtime dependencies are `httpx` and `pydantic` only.

## Quickstart

Set the provider and its key, then build the client from the environment:

```bash
export VOICE_PROVIDER=vapi        # or retell
export VAPI_API_KEY=...           # or RETELL_API_KEY
```

```python
import os

from voxbridge import Agent, VoiceClient

with VoiceClient.from_env() as client:
    agent = client.create_agent(Agent(
        name="Front desk",
        system_prompt="You are a friendly receptionist. Keep answers short.",
        model="gpt-4o",
        voice="openai:alloy",          # "<tts-provider>:<voiceId>"
        first_message="Hi, how can I help?",
    ))
    call = client.create_call(
        agent.id, "+15551234567", from_number=os.environ.get("FROM_NUMBER")
    )
    print(call.id, call.status)
```

`from_number` is required on Retell; on Vapi it is optional and looked up among
your phone numbers. The explicit form takes the same options:

```python
from voxbridge import VoiceClient

client = VoiceClient(provider="retell", api_key="key_...", webhook_secret="key_...")
```

Every method has an `a`-prefixed awaitable twin (`await client.acreate_call(...)`).
See the [quickstart guide](https://aquib.github.io/voxbridge/quickstart/) for
agents with tools, async usage and more.

## Configuration

| Setting | Constructor kwarg | Environment variable | Default |
| --- | --- | --- | --- |
| Provider | `provider` | `VOICE_PROVIDER` | required |
| API key | `api_key` | `VAPI_API_KEY` / `RETELL_API_KEY` | required |
| Webhook secret | `webhook_secret` | `VAPI_WEBHOOK_SECRET` / `RETELL_WEBHOOK_SECRET` | Vapi: none (unsigned accepted); Retell: the API key |
| Replay window (Retell only) | `webhook_max_age` | `RETELL_WEBHOOK_MAX_AGE` | `300` seconds; `None` disables |
| HTTP timeout | `timeout` | none | `30` seconds |

Keyword arguments to `from_env(**overrides)` win over environment values. Empty
variables count as unset. voxbridge does not load `.env` files itself; see the
[configuration guide](https://aquib.github.io/voxbridge/configuration/).

## Webhooks and tools

`parse_webhook` verifies the request and returns one normalized event;
`tool_response` builds the reply a provider expects for a tool call.

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from voxbridge import SignatureError, ToolCall, VoiceClient

app = FastAPI()
client = VoiceClient.from_env()


@app.post("/tools")
async def tools(request: Request) -> JSONResponse:
    try:
        event = client.parse_webhook(request.headers, await request.body())
    except SignatureError:
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    if isinstance(event, ToolCall) and event.name == "book_appointment":
        return JSONResponse(client.tool_response(event, {"booked": event.arguments.get("day")}))
    return JSONResponse({"error": "unknown tool"}, status_code=400)
```

> **Vapi is unauthenticated unless you set `VAPI_WEBHOOK_SECRET`.** Without a
> secret, anyone who finds your URL can post fake events or trigger your tools.
> Retell is verified by default with your API key.

A fuller, runnable server (webhooks and tools) is in
[`examples/`](examples/); the
[webhooks guide](https://aquib.github.io/voxbridge/webhooks/) covers verification,
event mapping and per-provider limits.

## Error handling

All errors derive from `VoxBridgeError`.

| Exception | Raised when |
| --- | --- |
| `AuthError` | the provider returns 401/403 |
| `RateLimited` | the provider returns 429; `.retry_after` is the seconds it asked you to wait, if given |
| `ProviderError` | any other failed or unusable response; `.status_code`, `.body`, `.provider` |
| `NotSupported` | the capability does not exist on the selected provider |
| `SignatureError` | a webhook failed signature verification |

`AuthError` and `RateLimited` are subclasses of `ProviderError`. Each request is
retried at most once: connect errors, connect timeouts and 429s for any request,
read/write timeouts, 5xx and other transport errors for idempotent requests
only, honouring `Retry-After` up to 10 seconds.

```python
from voxbridge import RateLimited, VoiceClient

client = VoiceClient.from_env()
try:
    client.get_call("call_123")
except RateLimited as exc:
    print("retry in", exc.retry_after)
```

## Vapi vs Retell

| | Vapi | Retell |
| --- | --- | --- |
| Auth header | `Authorization: Bearer` | `Authorization: Bearer` |
| Agent create | 1 API call | 2 API calls (LLM, then agent) |
| `list_calls()` default size | 100 | 50 (`limit` up to 1000) |
| `list_calls` items carry a transcript | yes | no, use `get_call` |
| Webhook verification | only if you set a secret | always, HMAC-SHA256 with the API key by default |
| Replay protection | not available | yes, `webhook_max_age` (default 300s) |
| Tool-call reply | `{"results": [{"toolCallId", "result"}]}`, single-line string | the result itself as the response body |
| Voice id on the wire | `{provider, voiceId}` | `"<provider>-<voiceId>"` |
| `Call.from_number` | the Vapi phone-number id | the number |

Voice ids are always written `"<tts-provider>:<voiceId>"` (`elevenlabs` is
normalized to `11labs`), but the voice catalogs differ between providers. See
[providers](https://aquib.github.io/voxbridge/providers/) for the full matrix
and known differences.

## More

- [Documentation](https://aquib.github.io/voxbridge/)
- [Changelog](https://github.com/Aquib/voxbridge/blob/main/CHANGELOG.md)
- [Contributing](https://github.com/Aquib/voxbridge/blob/main/CONTRIBUTING.md)

## License

[MIT](https://github.com/Aquib/voxbridge/blob/main/LICENSE)
