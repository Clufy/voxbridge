# Quickstart

## Create a client

Set the provider and its key in the environment and build the client from it:

```bash
export VOICE_PROVIDER=vapi        # or retell
export VAPI_API_KEY=...           # or RETELL_API_KEY
```

```python
from voxbridge import VoiceClient

client = VoiceClient.from_env()
```

The explicit form takes the same options (see [Configuration](configuration.md)):

```python
client = VoiceClient(provider="vapi", api_key="sk-...")  # or provider="retell"
```

Unknown provider names raise `ValueError`. The client is a context manager and
`close()` runs on exit:

```python
with VoiceClient.from_env() as client:
    ...
```

## Create an agent

```python
from voxbridge import Agent, Tool

agent = client.create_agent(Agent(
    name="Scheduler",
    system_prompt="You are a friendly scheduling assistant.",
    model="gpt-4o",
    voice="elevenlabs:rachel",       # "<tts-provider>:<voiceId>"
    first_message="Hi, this is Scheduler. How can I help?",
    tools=[Tool(
        name="book_appointment",
        description="Book an appointment slot",
        parameters={"type": "object", "properties": {"day": {"type": "string"}}},
        endpoint_url="https://example.com/tools/book",
    )],
))
print(agent.id)          # provider-assigned id
print(agent.raw)         # the untouched provider payload
```

The same `Agent` works on either provider; voxbridge maps the prompt, voice and
tools into each provider's native shape. Voice ids are `"<tts-provider>:<voiceId>"`
(`elevenlabs` is normalized to `11labs`), but the voice catalogs differ between
providers, so check the voice exists on the one you use. Retell stores the prompt
on a separate LLM object, so `create_agent` makes two API calls there; see
[Providers](providers.md) for what that means for updates and failures.

## Place a call

```python
call = client.create_call(agent.id, "+15550000000", from_number="+15550000001")
call = client.get_call(call.id)
print(call.status, call.transcript)

for c in client.list_calls(limit=20):
    print(c.id, c.status)
```

Outbound calls need a caller number (`from_number`) on both providers. Retell
raises `ValueError` without it. On Vapi, pass an E.164 number, looked up among
your phone numbers (`ProviderError` if none matches), or a phone-number id.

## Handle a webhook

`parse_webhook` verifies the request and normalizes it to a `WebhookEvent`. Pass
the raw body bytes, not re-serialized JSON:

```python
from voxbridge import CallEnded, ToolCall, TranscriptChunk

event = client.parse_webhook(request.headers, raw_body)
match event:
    case CallEnded(call_id=cid, transcript=t, ended_reason=r):
        ...
    case TranscriptChunk(role=role, text=text):
        ...
    case ToolCall(name=name, arguments=args):
        reply = client.tool_response(event, {"ok": True})  # return as the HTTP 200 JSON body
```

A failed verification raises `SignatureError`; a malformed body raises
`ProviderError`. Verification rules differ per provider (Vapi accepts unsigned
requests unless you set a secret), so read [Webhooks & tools](webhooks.md) before
going to production. A runnable FastAPI server is in
[`examples/fastapi_server.py`](https://github.com/Clufy/voxbridge/blob/main/examples/fastapi_server.py).

## Async

Every agent/call method has an `a`-prefixed async twin with the same signature
(`parse_webhook`, `verify_signature` and `tool_response` are sync):

```python
async with VoiceClient.from_env() as client:
    agent = await client.acreate_agent(Agent(
        name="Scheduler", system_prompt="Be brief.", model="gpt-4o", voice="openai:alloy",
    ))
    call = await client.aget_call("call_123")
    calls = await client.alist_calls()
```

`parse_webhook`, `verify_signature` and `tool_response` stay synchronous; they do
no I/O.

## Handle errors

```python
from voxbridge import AuthError, NotSupported, ProviderError, RateLimited

try:
    client.get_call("call_123")
except RateLimited as exc:
    print("retry in", exc.retry_after)
except AuthError:
    print("check your API key")
except ProviderError as exc:
    print(exc.status_code, exc.body)
except NotSupported as exc:
    print("not available on this provider:", exc)
```

`AuthError` and `RateLimited` subclass `ProviderError`, so catch them first. Each
request is retried at most once; see the [API reference](api.md) for the exact
policy.
