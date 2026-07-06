# voxbridge

One interface over multiple voice-agent platforms. Write your integration once
against `voxbridge`; switch between [Vapi](https://vapi.ai) and
[Retell](https://retellai.com) with a config string.

## Why

Voice-agent platforms diverge on nearly everything — auth, endpoint prefixes,
where the system prompt lives, webhook envelopes, signature schemes. voxbridge
absorbs those differences behind one small, typed surface:

- **One API, many providers** — agents, calls, tools, and webhooks through a
  single `VoiceClient`.
- **Typed domain models** — Pydantic v2 `Agent` / `Call` / `Tool`; every model
  keeps the untouched provider payload under `.raw`, so nothing is lost.
- **Normalized webhooks** — each provider's webhook envelope maps to one
  `WebhookEvent` union, with per-provider signature verification.
- **Sync and async** — every call has an `a`-prefixed awaitable twin.
- **No silent gaps** — a capability missing on a provider raises `NotSupported`,
  never a no-op.

## Install

```bash
pip install voxbridge
```

Runtime dependencies are `httpx` and `pydantic` only. Requires Python 3.12+.

## Next steps

- [Quickstart](quickstart.md) — create an agent, place a call, handle a webhook.
- [Providers](providers.md) — the Vapi-vs-Retell capability matrix and the
  per-provider details voxbridge normalizes away.
