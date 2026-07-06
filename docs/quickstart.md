# Quickstart

## Create a client

```python
from voxbridge import VoiceClient

client = VoiceClient(provider="vapi", api_key="sk-...")  # or provider="retell"
```

Unknown provider strings raise `ValueError`. The client is a context manager:

```python
with VoiceClient(provider="vapi", api_key="sk-...") as client:
    ...  # client.close() runs on exit
```

## Create an agent

```python
from voxbridge import Agent, Tool

agent = client.create_agent(Agent(
    name="Scheduler",
    system_prompt="You are a friendly scheduling assistant.",
    model="gpt-4o",
    voice="elevenlabs:rachel",       # "provider:voiceId", or a bare voice id
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

The same `Agent` works for either provider — voxbridge maps the prompt, voice,
and tools into each provider's native shape (for Retell, that means creating the
separate LLM object and the agent that references it, in two API calls).

## Place a call

```python
call = client.create_call(agent.id, to_number="+15550000000", from_number="+15550000001")
call = client.get_call(call.id)
print(call.status, call.transcript)

for c in client.list_calls():
    print(c.id, c.status)
```

## Handle a webhook

`parse_webhook` verifies the signature (when a `webhook_secret` is configured)
and normalizes the payload to a `WebhookEvent`:

```python
from voxbridge import CallEnded, TranscriptChunk, ToolCall

client = VoiceClient(provider="vapi", api_key="sk-...", webhook_secret="whsec_...")

event = client.parse_webhook(request.headers, request.body)  # raw bytes
match event:
    case CallEnded(call_id=cid, transcript=t, ended_reason=r):
        ...
    case TranscriptChunk(role=role, text=text):
        ...
    case ToolCall(name=name, arguments=args, tool_call_id=tid):
        ...
```

A tampered body (bad signature) raises `SignatureError`; a malformed body raises
`ProviderError`. For Retell, enable replay protection with `webhook_max_age`:

```python
client = VoiceClient(
    provider="retell", api_key="sk-...",
    webhook_secret="whsec_...", webhook_max_age=300,   # reject signatures > 5 min old
)
```

## Async

Every method has an `a`-prefixed awaitable twin with the same signature:

```python
async with VoiceClient(provider="retell", api_key="sk-...") as client:
    agent = await client.acreate_agent(Agent(...))
    call = await client.aget_call("call_123")
    calls = await client.alist_calls()
```

`parse_webhook` and `verify_signature` stay synchronous — they do no I/O.
