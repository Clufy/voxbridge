# voxbridge

voxbridge is a Python SDK that puts one typed `VoiceClient` over the
[Vapi](https://vapi.ai) and [Retell](https://retellai.com) voice-agent
platforms. Create agents, place outbound calls, verify and parse webhooks, and
answer tool calls with the same code on either provider; switching is a config
string.

## Why

Voice-agent platforms diverge on nearly everything: endpoint prefixes, where the
system prompt lives, webhook envelopes, signature schemes, voice-id formats.
voxbridge absorbs those differences behind one small surface:

- **One API, many providers**: agents, calls, tools and webhooks through a
  single `VoiceClient`.
- **Typed domain models**: Pydantic v2 `Agent`, `Call` and `Tool`; every model
  keeps the untouched provider payload under `.raw`.
- **Normalized webhooks**: each provider's envelope maps to one `WebhookEvent`
  union, with per-provider signature verification.
- **Sync and async**: every method has an `a`-prefixed awaitable twin.
- **No silent gaps**: a capability a provider lacks raises `NotSupported`.

## Install

```bash
pip install voxbridge
```

Requires Python 3.12+. Runtime dependencies are `httpx` and `pydantic` only.

## Where next

- [Quickstart](quickstart.md): create an agent, place a call, handle a webhook.
- [Configuration](configuration.md): constructor options and environment variables.
- [Webhooks & tools](webhooks.md): verification, event mapping, answering tool calls.
- [Providers](providers.md): the Vapi-vs-Retell matrix and the differences that can bite you.
- [API reference](api.md) and the [Changelog](changelog.md).
