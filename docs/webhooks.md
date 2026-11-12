# Webhooks & tools

Providers push call events and tool invocations to HTTP endpoints you host.
voxbridge verifies each request, normalizes it to one `WebhookEvent`, and builds
the reply a tool call needs. The calls are synchronous and do no I/O:

```python
event = client.parse_webhook(headers, raw_body)   # verifies, then parses
```

Always pass the **raw request body bytes**. Signatures are computed over the
exact bytes the provider sent, so re-serialized JSON will fail verification.
`client.verify_signature(headers, raw_body)` returns a bool if you want to check
without parsing.

A runnable FastAPI server that handles both webhooks and tool calls is in
[`examples/fastapi_server.py`](https://github.com/Clufy/voxbridge/blob/main/examples/fastapi_server.py).

## Verification

| | Vapi | Retell |
| --- | --- | --- |
| Verified by default | **No** | Yes |
| Mechanism | `X-Vapi-Secret` header equal to your secret, or `Authorization: Bearer <secret>` | `x-retell-signature: v={ts},d={hex}`, HMAC-SHA256 over `raw_body + ts` |
| Key used | `webhook_secret` (`VAPI_WEBHOOK_SECRET`) | `webhook_secret` (`RETELL_WEBHOOK_SECRET`), otherwise the API key |
| Replay protection | none (no timestamp) | rejects signatures older than `webhook_max_age` (default 300 s; `None` disables) |
| Failure | `SignatureError` | `SignatureError` |

!!! danger "Vapi webhooks are unsigned unless you set a secret"
    With no `webhook_secret`, voxbridge accepts every Vapi request, including
    forged ones. If you serve tool calls, anyone who finds the URL can run your
    tools. Always set `VAPI_WEBHOOK_SECRET` (and the matching credential on the
    Vapi side) in production. Vapi's HMAC credential is not supported in 0.1.0.

!!! note "Retell: use the webhook-badged key"
    Retell signs with the API key that has the webhook badge in the Retell
    dashboard. With no `webhook_secret`, voxbridge uses `api_key`, which is
    correct only if that key is the badged one. Otherwise pass the badged key
    as `webhook_secret`.

Passing `webhook_max_age` for Vapi raises `NotSupported`.

## Event mapping

Both providers fold into one union: `CallStarted`, `CallEnded`, `TranscriptChunk`,
`ToolCall` and `ErrorEvent`. Every event has `call_id`, `provider` and the full
payload under `raw`.

| Event | Vapi `message.type` | Retell `event` |
| --- | --- | --- |
| `CallStarted` | `status-update` (any status except `ended`) | `call_started` |
| `CallEnded` | `end-of-call-report`; `status-update` with `ended` | `call_ended`, `call_analyzed` |
| `TranscriptChunk` | `transcript` | `transcript_updated` (newest turn) |
| `ToolCall` | `tool-calls` | a custom-function request (`name`, `args`, `call`) |
| `ErrorEvent` | any other type | any other event |

`ErrorEvent` is also what you get for event types voxbridge does not map, with
the type named in `message`, so handle it by logging, not by failing the request.
Speaker roles are normalized: Retell's `agent` becomes `assistant`.

!!! tip "Dedupe on `call_id`"
    One call can produce several `CallEnded` events (Vapi: a status update plus
    the end-of-call report; Retell: `call_ended` and the richer `call_analyzed`).
    Treat `call_id` as the idempotency key and keep the event with the transcript.

## Tool calls

Declare a tool with `Tool(..., endpoint_url="https://your.host/tools")`, then
answer the request your endpoint receives:

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
    if not isinstance(event, ToolCall):
        return JSONResponse({"error": "not a tool call"}, status_code=400)
    result = {"booked": event.arguments.get("day")}
    return JSONResponse(client.tool_response(event, result))   # HTTP 200
```

!!! note "Vapi tool endpoints and `VAPI_WEBHOOK_SECRET`"
    voxbridge registers Vapi tools with `server.url` only. If your tool endpoint
    verifies with `VAPI_WEBHOOK_SECRET`, configure the matching server
    secret/credential on the assistant or tool in Vapi. An existing one is
    preserved when voxbridge updates the agent.

`ToolCall` carries `name`, `arguments` (a dict) and `tool_call_id`. Send the value
of `client.tool_response(event, result)` back as the JSON body with status 200;
`result` must be JSON-serializable.

| | Vapi | Retell |
| --- | --- | --- |
| Request | `tool-calls` message; `tool_call_id` is Vapi's id | POST `{"name", "args", "call"}`; `tool_call_id` is `None` |
| Reply body | `{"results": [{"toolCallId": ..., "result": "..."}]}` | the result itself |
| Result format | a **single-line string**: non-strings are compact-JSON encoded, newlines become spaces | a dict stays a JSON object (Retell can map it to response variables); other values are returned as-is |

## Limitations

- **Vapi, multiple tool calls in one message**: only the first is surfaced as the
  `ToolCall`; the rest stay in `event.raw`.
- **Retell `args_at_root`** (a tool option that sends the bare arguments as the
  body) is not supported, because such a body cannot be told apart from any other
  payload. Leave it off.
- **Retell result size**: Retell truncates tool results at 15,000 characters by
  default. voxbridge documents this but does not enforce it.
- **Vapi HMAC credentials** are not supported; use the shared secret or Bearer
  form.
- Malformed bodies (not UTF-8 JSON, not a JSON object, or fields of the wrong
  type) raise `ProviderError`, never a bare decode or attribute error.
