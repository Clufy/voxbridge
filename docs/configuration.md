# Configuration

## Constructor

```python
from voxbridge import VoiceClient

client = VoiceClient(
    provider="retell",
    api_key="key_...",
    webhook_secret="key_...",   # optional
    webhook_max_age=300,        # Retell only, optional
    timeout=30,                 # optional
)
```

| Argument | Default | Meaning |
| --- | --- | --- |
| `provider` | required | `"vapi"` or `"retell"`; anything else raises `ValueError`. |
| `api_key` | required | The provider API key, sent as `Authorization: Bearer`. |
| `webhook_secret` | none | Secret used to verify webhooks. On Vapi, leaving it unset means webhooks are **not** verified. On Retell it falls back to the API key. |
| `webhook_max_age` | `300` (Retell) | Retell only. Maximum age of a webhook signature in seconds; `None` disables the replay check. Passing it for Vapi raises `NotSupported`, because Vapi signatures carry no timestamp. |
| `timeout` | `30` | Per-request HTTP timeout in seconds. |

## From the environment

`VoiceClient.from_env()` reads:

| Variable | Used for |
| --- | --- |
| `VOICE_PROVIDER` | Provider name (skipped if you pass `provider=`). |
| `VAPI_API_KEY` / `RETELL_API_KEY` | `api_key`. Required. |
| `VAPI_WEBHOOK_SECRET` / `RETELL_WEBHOOK_SECRET` | `webhook_secret`. |
| `RETELL_WEBHOOK_MAX_AGE` | `webhook_max_age`, a number. Setting `VAPI_WEBHOOK_MAX_AGE` raises `NotSupported`. |

Empty values count as unset. A missing provider or key, an unknown provider, or a
non-numeric max age raises `ValueError` with a message naming the variable.

```python
VoiceClient.from_env()                       # provider from VOICE_PROVIDER
VoiceClient.from_env("vapi")                 # explicit provider
VoiceClient.from_env("retell", timeout=60)   # keyword overrides win over the environment
VoiceClient.from_env(environ={"VOICE_PROVIDER": "vapi", "VAPI_API_KEY": "sk-..."})  # custom mapping
```

## Where the variables come from

voxbridge reads `os.environ` and nothing else; it does not load `.env` files.
Either export the variables in your shell or deployment platform, or load a
`.env` yourself before building the client with
[`python-dotenv`](https://pypi.org/project/python-dotenv/):

```python
from dotenv import load_dotenv

from voxbridge import VoiceClient

load_dotenv()                  # copies .env entries into os.environ
client = VoiceClient.from_env()
```

`python-dotenv` is not a voxbridge dependency; install it yourself
(`pip install python-dotenv`). Keep `.env` out of version control.

## Retell webhook key

Retell signs webhooks with an API key that carries the **webhook badge** in the
Retell dashboard. When you don't pass a `webhook_secret`, voxbridge verifies with
`api_key`, which only works if that key is the badged one. If your API key is not
badged, pass the badged key as `webhook_secret` (or set `RETELL_WEBHOOK_SECRET`).
